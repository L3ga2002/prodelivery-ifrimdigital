"""Read contract tests; Mongo cases reuse the verified owned 27941 fixture."""

import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import quote

from bson import ObjectId
from bson.decimal128 import Decimal128
from bson.datetime_ms import DatetimeMS
from bson.int64 import Int64
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pymongo.errors import OperationFailure
import pytest

from test_order_creation_recovery import db, mongo_case
import utils.order_reads as reads
from utils.order_reads import OrderReadService, safe_order, safe_history, safe_date
from utils.order_assignment import MULTI_FIELDS


ADMIN = {"id": "qa-read-admin", "role": "admin"}
RESTAURANT = {"id": "qa-read-restaurant-user", "role": "restaurant", "restaurant_id": "qa-read-restaurant"}
DRIVER = {"id": "qa-read-driver-user", "role": "driver"}
FOREIGN = {"id": "qa-read-foreign", "role": "restaurant", "restaurant_id": "qa-read-other"}
NOW = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
SECRET = "QA-DO-NOT-EXPOSE-RAW-SECRET"


def order(**changes):
    return {"id": "qa-read-order", "order_number": "S.1200", "source": "S",
            "restaurant_id": RESTAURANT["restaurant_id"], "restaurant_name": "QA Restaurant",
            "driver_id": "qa-read-driver", "driver_name": "QA Driver",
            "customer_name": "QA Customer", "customer_phone": "0700000000",
            "customer_address": "QA Synthetic Address", "status": "NEW",
            "payment_type": "CASH", "total_amount": 34.5,
            "created_at": NOW, "updated_at": NOW, "items": [], **changes}


class FakeCursor:
    def __init__(self, documents, fault=None, delay=0):
        self.documents, self.fault, self.delay = deepcopy(documents), fault, delay
        self.closed = False

    async def to_list(self, length):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fault:
            raise self.fault
        return self.documents[:length]

    async def close(self):
        self.closed = True


class FakeCollection:
    """Static boundary fake, deliberately does not emulate Mongo aggregation."""
    def __init__(self, documents=(), *, fault=None, delay=0):
        self.documents, self.fault, self.delay = documents, fault, delay
        self.calls, self.cursors = [], []

    def aggregate(self, pipeline, **kwargs):
        self.calls.append((pipeline, kwargs))
        cursor = FakeCursor(self.documents, self.fault, self.delay)
        self.cursors.append(cursor)
        return cursor


def fake_db(actor=ADMIN, documents=(), **faults):
    return SimpleNamespace(users=FakeCollection([actor]), orders=FakeCollection(documents, **faults),
                           drivers=FakeCollection([{"id": "qa-read-driver", "user_id": DRIVER["id"]}]))


def projected(document):
    value = deepcopy(document)
    value.setdefault("_id", ObjectId())
    value["_read_date"] = safe_date(value.get("created_at"))
    value["_read_id"] = value.get("id", "")
    value["_read_has_revision"] = "order_version" in document
    value["_read_has_preparation_status"] = "preparation_status" in document
    value["_read_multi_fields"] = [name for name in MULTI_FIELDS if name in document]
    return value


def detail_document(document, entries=()):
    return {**projected(document), "_history": list(entries), "_history_start": 0,
            "_history_end": len(entries), "_history_invalid": False}


@pytest.fixture
def routes(monkeypatch):
    auth = ModuleType("auth")

    async def unauthenticated(*args, **kwargs):
        raise HTTPException(401, "Authentication required")

    auth.get_current_user = unauthenticated
    monkeypatch.setitem(sys.modules, "auth", auth)
    path = Path(__file__).resolve().parents[1] / "routers/orders.py"
    spec = importlib.util.spec_from_file_location("_pd_s206_read_routes", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


async def http(routes, database, path, actor=ADMIN, **kwargs):
    routes.db = database
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    if actor is not None:
        async def authenticated(*args, **unused):
            return actor
        routes.get_current_user = authenticated
        kwargs["headers"] = {"X-Expected-Actor-ID": actor["id"], **kwargs.get("headers", {})}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
        return await client.get("/api/orders" + path, **kwargs)


@pytest.mark.parametrize("value,expected", [(NOW, NOW), ("2026-10-08T12:00:00+02:00", NOW),
    ("2026-10-08T10:00:00Z", NOW), ("2026-10-08 10:00:00", NOW),
    ("2026-10-08", datetime(2026, 10, 8, tzinfo=timezone.utc)), ("bad", None),
    ("2026-99-99", None), (0, None), (True, None), ({"date": SECRET}, None), (None, None)])
def test_safe_date_mixed_legacy_values(value, expected):
    assert safe_date(value) == expected


@pytest.mark.parametrize("revision", [None, True, False, "7", {}, [], -1, 1.2, reads.MAX_ORDER_VERSION + 1])
def test_protected_revision_presence_malformed_is_null_not_legacy(revision):
    warnings = set()
    output = safe_order(order(order_version=revision), warnings)
    assert "order_version" in output and output["order_version"] is None
    assert "ORDER_VERSION_INVALID" in warnings and output["read_actions_unavailable"] is True


def test_protected_legacy_has_no_revision_key_and_valid_revision_zero_is_preserved():
    for document in (order(), projected(order())):
        warnings = set()
        output = safe_order(document, warnings)
        assert "order_version" not in output
        assert not output["read_actions_unavailable"] and not warnings
    output = safe_order(order(order_version=0), set())
    assert output["order_version"] == 0 and not output["read_actions_unavailable"]


@pytest.mark.parametrize("name", MULTI_FIELDS)
def test_multislot_metadata_is_fail_closed_without_raw_values(name):
    warnings = set()
    output = safe_order(order(**{name: {"raw": SECRET}}), warnings)
    assert name in output and output[name] is None
    assert output["read_actions_unavailable"] and "ORDER_ASSIGNMENT_UNSUPPORTED" in warnings
    assert SECRET not in json.dumps(output)


def test_safe_projection_no_internal_ledger_or_raw_nested_data():
    warnings = set()
    output = safe_order(order(customer_phone={"password": SECRET}, status=[SECRET],
                              audit_trail=[{"token": SECRET}], operation_ref=SECRET, secret=SECRET), warnings)
    assert output["customer_phone"] is None and output["status"] is None
    assert "audit_trail" not in output and "operation_ref" not in output and "secret" not in output
    assert SECRET not in json.dumps(output) and "ORDER_STATUS_UNAVAILABLE" in warnings


def test_safe_history_only_approved_scalars_and_no_html():
    warnings = set()
    output = safe_history({"index": 4, "action": "order.corrected", "created_at": NOW,
        "performed_by": "qa-read-admin", "performed_by_role": "admin", "from_order_version": 0,
        "to_order_version": 1, "token": SECRET, "operation_ref": SECRET,
        "changes": {"fields": ["notes", "customer_phone", SECRET], "to_status": "READY",
                    "notes": "<script>" + SECRET + "</script>", "customer_name": {"token": SECRET},
                    "credentials": SECRET}}, warnings)
    assert output["changes"] == {"to_status": "READY", "fields": "customer_phone, notes"}
    assert "HISTORY_FIELD_INVALID" in warnings and SECRET not in json.dumps(output)


@pytest.mark.parametrize("kwargs", [
    {"view": "x"}, {"view": {}}, {"status": "UNKNOWN"}, {"status": []},
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "1.0"}, {"limit": "01"},
    {"restaurant_id": ""}, {"driver_id": " driver"}, {"driver_id": {"$ne": None}},
    {"from_date": "2026-10-08"}, {"from_date": "2026-10-08T10:00:00+02:00"},
    {"to_date": "invalid"}, {"from_date": "2026-10-08T10:00:00Z", "to_date": "2026-10-08T10:00:00Z"},
])
def test_page_invalid_inputs_are_safe_422_before_database(kwargs):
    database = fake_db()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(OrderReadService(database).page(ADMIN, **kwargs))
    assert caught.value.status_code == 422 and not database.users.calls
    assert caught.value.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("kwargs", [{"history_limit": 0}, {"history_limit": 51}, {"history_limit": True},
    {"history_before": -1}, {"history_before": "-1"}, {"history_before": "1.2"},
    {"history_before": True}, {"history_before": "99999999999999999999"}])
def test_detail_invalid_pagination_is_safe_422_before_database(kwargs):
    database = fake_db()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(OrderReadService(database).detail(ADMIN, "qa-read-order", **kwargs))
    assert caught.value.status_code == 422 and not database.users.calls


@pytest.mark.parametrize("expected,status", [("different-actor", 403), ("", 422), (" qa", 422), ("bad\x00actor", 422)])
def test_expected_actor_comparison_before_any_business_read(expected, status):
    database = fake_db()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(OrderReadService(database).page(ADMIN, expected_actor_id=expected))
    assert caught.value.status_code == status and not database.users.calls and not database.orders.calls


def test_service_deadlines_max_time_no_leaky_logs_and_cursor_cleanup(monkeypatch, caplog):
    for faults in ({"fault": OperationFailure(SECRET)}, {"delay": 0.2}):
        database = fake_db(**faults)
        monkeypatch.setattr(reads, "READ_TIMEOUT_SECONDS", 0.02)
        with pytest.raises(HTTPException) as caught:
            asyncio.run(OrderReadService(database).page(ADMIN))
        assert caught.value.status_code == 503
        assert caught.value.detail["code"] == "READ_UNAVAILABLE"
        assert SECRET not in str(caught.value.detail) and SECRET not in caplog.text
        assert all(cursor.closed for cursor in database.orders.cursors)
        for _, options in database.users.calls + database.orders.calls:
            assert options["maxTimeMS"] == 3000 and options["allowDiskUse"] is False


def test_cursor_validation_filter_actor_scope_and_checksum_binding():
    documents = [projected(order(order_number="1")), projected(order(order_number="2"))]
    first = asyncio.run(OrderReadService(fake_db(documents=documents)).page(ADMIN, limit=1))
    cursor = first["next_cursor"]
    assert first["has_more"] and cursor and SECRET not in cursor
    for kwargs in ({"view": "all"}, {"limit": 2}, {"status": "NEW"}, {"restaurant_id": "other"},
                   {"driver_id": "other"}, {"from_date": "2026-10-08T10:00:00Z"}):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(OrderReadService(fake_db()).page(ADMIN, cursor=cursor, **{"limit": 1, **kwargs}))
        assert caught.value.status_code == 422
    other = {**ADMIN, "id": "qa-other-admin"}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(OrderReadService(fake_db(other)).page(other, cursor=cursor, limit=1))
    assert caught.value.status_code == 422
    decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    decoded["data"]["id"] = "tampered"
    tampered = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode().rstrip("=")
    for invalid in ("", "%%", "a" * 4097, tampered):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(OrderReadService(fake_db()).page(ADMIN, cursor=invalid, limit=1))
        assert caught.value.status_code == 422 and caught.value.detail["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize("path", ["/read/page", "/read/detail/qa-read-order"])
def test_http_success_frozen_envelopes_and_no_store(routes, path):
    database = fake_db(documents=[detail_document(order()) if "detail" in path else projected(order())])
    response = asyncio.run(http(routes, database, path))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    expected = ({"order", "history", "next_history_before", "history_has_more", "data_warnings"} if "detail" in path
                else {"items", "next_cursor", "has_more", "limit", "data_warnings"})
    assert set(response.json()) == expected
    value = response.json()["order"] if "detail" in path else response.json()["items"][0]
    assert "order_version" not in value


@pytest.mark.parametrize("path", ["/read/page?limit=0", "/read/page?limit=abc", "/read/page?view=bad",
    "/read/page?driver_id=", "/read/page?limit=1&limit=2", "/read/page?unexpected=secret",
    "/read/detail/qa-read-order?history_before=-1", "/read/detail/qa-read-order?history_limit=51"])
def test_http_invalid_request_is_sanitized_no_store(routes, path):
    database = fake_db()
    response = asyncio.run(http(routes, database, path))
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    assert set(response.json()["detail"]) == {"code", "message"}
    assert not database.orders.calls


def test_http_auth_failure_timeout_and_switched_actor_no_business_reads(routes, monkeypatch):
    database = fake_db()
    response = asyncio.run(http(routes, database, "/read/page", actor=None))
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    response = asyncio.run(http(routes, database, "/read/page", headers={"X-Expected-Actor-ID": "other"}))
    assert response.status_code == 403 and not database.orders.calls
    async def stalled(*args):
        await asyncio.sleep(1)
    routes.get_current_user = stalled
    monkeypatch.setattr(routes, "READ_TIMEOUT_SECONDS", 0.01)
    response = asyncio.run(http(routes, database, "/read/page", actor=None))
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"


def test_legacy_date_formatter_invalid_null_valid_behavior_preserved(routes):
    valid_naive = "2026-10-08T10:00:00"
    original = {"created_at": valid_naive, "updated_at": "malformed"}
    result = routes._format_order_dates(original)
    assert result["created_at"] == datetime.fromisoformat(valid_naive)
    assert result["created_at"].tzinfo is None and result["updated_at"] is None
    original = {"created_at": "bad", "updated_at": NOW}
    assert routes._format_order_dates(original) == {"created_at": None, "updated_at": NOW}
    for invalid in ([], {}, True, 123):
        assert routes._format_order_dates({"created_at": invalid})["created_at"] is None


async def seed(database, documents=()):
    await database.users.insert_many([{**actor, "email": actor["id"] + "@synthetic.invalid", "name": "QA User"}
                                      for actor in (ADMIN, RESTAURANT, DRIVER, FOREIGN)])
    await database.drivers.insert_one({"id": "qa-read-driver", "user_id": DRIVER["id"], "account_disabled": False})
    if documents:
        await database.orders.insert_many(documents)


async def snapshot(database):
    return {name: await database[name].find({}).sort("_id", 1).to_list(None)
            for name in await database.list_collection_names()}


@mongo_case
async def test_mongo_over_1000_mixed_dates_equal_ids_pk_ties_last_page_readonly(db):
    dates = [NOW, "2026-10-08T10:00:00Z", "2026-10-08T12:00:00+02:00",
             "2026-10-08 10:00:00", "2026-10-07T10:00:00Z", "bad", None, {}, 123, True]
    documents = [order(_id=ObjectId(f"{index:024x}"), id=f"qa-order-{index // 3:04d}",
        order_number=f"S.{index:04d}", created_at=dates[index % len(dates)], secret=SECRET,
        audit_trail=[{"secret": SECRET}], operation_ref=SECRET) for index in range(1207)]
    documents.append(order(_id="qa-string-pk", id="qa-string", created_at=NOW))
    documents.append(order(_id=9, id="qa-int-pk", created_at=NOW))
    await seed(db, documents)
    before = await snapshot(db)
    service = OrderReadService(db)
    cursor = None
    collected, warnings = [], set()
    for _ in range(20):
        page = await service.page(ADMIN, view="all", limit=100, cursor=cursor)
        assert page["limit"] == 100 and len(page["items"]) <= 100
        collected.extend(page["items"])
        warnings.update(page["data_warnings"])
        assert SECRET not in json.dumps(page)
        cursor = page["next_cursor"]
        assert page["has_more"] is (cursor is not None)
        if cursor is None:
            break
    assert len(collected) == 1209 and len({entry["order_number"] for entry in collected}) == 1207
    # The two special primary key rows share an order_number only, not a document.
    numbers = [entry["order_number"] for entry in collected if entry["order_number"] != "S.1200"]
    assert len(numbers) == len(set(numbers))
    expected = sorted(documents[:1207], key=lambda item: (
        safe_date(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), item["id"], str(item["_id"])), reverse=True)
    main = [entry for entry in collected if entry["id"] not in ("qa-int-pk", "qa-string")]
    assert [entry["order_number"] for entry in main] == [entry["order_number"] for entry in expected]
    assert all("order_version" not in entry for entry in collected)
    assert "ORDER_DATE_UNAVAILABLE" in warnings and await snapshot(db) == before


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT, DRIVER])
@mongo_case
async def test_mongo_legacy_list_detail_revision_missing_vs_invalid_owned(db, actor):
    await seed(db, [order(), order(id="qa-version-invalid", order_version="bad"),
                    order(id="qa-version-zero", order_version=0), order(id="qa-version-null", order_version=None)])
    service = OrderReadService(db)
    before = await snapshot(db)
    page = await service.page(actor, view="all")
    legacy = next(item for item in page["items"] if item["id"] == "qa-read-order")
    assert "order_version" not in legacy and not legacy["read_actions_unavailable"]
    detail = await service.detail(actor, "qa-read-order")
    assert "order_version" not in detail["order"] and not detail["order"]["read_actions_unavailable"]
    for name in ("qa-version-invalid", "qa-version-null"):
        value = next(item for item in page["items"] if item["id"] == name)
        assert "order_version" in value and value["order_version"] is None and value["read_actions_unavailable"]
        detail = await service.detail(actor, name)
        assert "order_version" in detail["order"] and detail["order"]["order_version"] is None
        assert "ORDER_VERSION_INVALID" in detail["data_warnings"]
    assert (await service.detail(actor, "qa-version-zero"))["order"]["order_version"] == 0
    assert await snapshot(db) == before


@mongo_case
async def test_mongo_views_filters_normalized_dates_and_cursor_tampering(db):
    await seed(db, [order(id="a", created_at="2026-10-08T10:00:00Z"),
                    order(id="b", status="DELIVERED", created_at=NOW),
                    order(id="c", status="CANCELLED", created_at="2026-10-08T12:00:00+02:00"),
                    order(id="d", created_at="2026-10-08T11:00:00Z"),
                    order(id="e", created_at="invalid"), order(id="f", restaurant_id="other")])
    service = OrderReadService(db)
    assert {item["id"] for item in (await service.page(ADMIN, view="active"))["items"]} == {"a", "d", "e", "f"}
    assert {item["id"] for item in (await service.page(ADMIN, view="history"))["items"]} == {"b", "c"}
    assert (await service.page(ADMIN, view="active", status="DELIVERED"))["items"] == []
    page = await service.page(ADMIN, view="all", restaurant_id=RESTAURANT["restaurant_id"],
                             from_date="2026-10-08T10:00:00Z", to_date="2026-10-08T11:00:00Z")
    assert {item["id"] for item in page["items"]} == {"a", "b", "c"}
    cursor = (await service.page(ADMIN, view="all", limit=1))["next_cursor"]
    for actor, kwargs in ((ADMIN, {"view": "active"}), (RESTAURANT, {"view": "all"}),
                          (ADMIN, {"view": "all", "driver_id": "other"})):
        with pytest.raises(HTTPException) as caught:
            await service.page(actor, cursor=cursor, limit=1, **kwargs)
        assert caught.value.status_code == 422


@mongo_case
async def test_mongo_driver_user_link_optional_consistency_and_foreign_scope(db):
    await seed(db, [order(), order(id="qa-foreign-order", restaurant_id=FOREIGN["restaurant_id"], driver_id="other")])
    service = OrderReadService(db)
    assert [item["id"] for item in (await service.page(DRIVER))["items"]] == ["qa-read-order"]
    assert [item["id"] for item in (await service.page(RESTAURANT))["items"]] == ["qa-read-order"]
    for actor in (DRIVER, RESTAURANT):
        with pytest.raises(HTTPException) as caught:
            await service.detail(actor, "qa-foreign-order")
        assert caught.value.status_code == 404
    with pytest.raises(HTTPException) as caught:
        await service.page(DRIVER, driver_id="other")
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as caught:
        await service.page(RESTAURANT, restaurant_id=FOREIGN["restaurant_id"])
    assert caught.value.status_code == 403
    await db.users.update_one({"id": DRIVER["id"]}, {"$set": {"driver_id": "wrong"}})
    with pytest.raises(HTTPException) as caught:
        await service.page(DRIVER)
    assert caught.value.status_code == 403
    await db.users.update_one({"id": DRIVER["id"]}, {"$unset": {"driver_id": ""}})
    with pytest.raises(HTTPException) as caught:
        await service.page({**DRIVER, "driver_id": "wrong"})
    assert caught.value.status_code == 403
    await db.drivers.insert_one({"id": "duplicate-link", "user_id": DRIVER["id"]})
    with pytest.raises(HTTPException) as caught:
        await service.page(DRIVER)
    assert caught.value.status_code == 403


@mongo_case
async def test_mongo_missing_ownership_never_matches_missing_and_auth_updates_fail_closed(db):
    await seed(db, [order(restaurant_id=None, driver_id=None)])
    service = OrderReadService(db)
    await db.users.update_one({"id": RESTAURANT["id"]}, {"$unset": {"restaurant_id": ""}})
    with pytest.raises(HTTPException) as caught:
        await service.detail({**RESTAURANT, "restaurant_id": None}, "qa-read-order")
    assert caught.value.status_code == 403
    await db.drivers.delete_one({"user_id": DRIVER["id"]})
    with pytest.raises(HTTPException) as caught:
        await service.detail(DRIVER, "qa-read-order")
    assert caught.value.status_code == 403
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"account_disabled": True}})
    with pytest.raises(HTTPException) as caught:
        await service.page(ADMIN)
    assert caught.value.status_code == 403


@mongo_case
async def test_mongo_history_index_anchor_new_append_no_raw_leaks_bounded_projection(db):
    entries = [{"id": f"audit-{index}", "action": "order.status_changed", "created_at": NOW,
                "performed_by": ADMIN["id"], "performed_by_role": "admin", "from_order_version": index,
                "to_order_version": index + 1, "changes": {"from_status": "NEW", "to_status": "READY"},
                "operation_ref": SECRET, "raw": SECRET * 5000} for index in range(67)]
    entries[64] = "malformed-entry"
    entries[63]["created_at"] = "not-a-date"
    entries[62]["changes"].update(credentials=SECRET, notes={"raw": SECRET})
    entries[61]["changes"]["fields"] = ["notes", SECRET]
    await seed(db, [order(order_version=67, audit_trail=entries, secret=SECRET)])
    service = OrderReadService(db)
    first = await service.detail(ADMIN, "qa-read-order", history_limit=10)
    assert [entry["index"] for entry in first["history"]] == list(range(66, 56, -1))
    assert first["next_history_before"] == 57 and first["history_has_more"]
    assert {"HISTORY_ENTRY_INVALID", "HISTORY_DATE_UNAVAILABLE", "HISTORY_FIELD_INVALID"} <= set(first["data_warnings"])
    assert SECRET not in json.dumps(first)
    await db.orders.update_one({"id": "qa-read-order"}, {"$push": {"audit_trail": entries[0]}})
    before = await snapshot(db)
    second = await service.detail(ADMIN, "qa-read-order", history_limit=10, history_before=first["next_history_before"])
    assert [entry["index"] for entry in second["history"]] == list(range(56, 46, -1))
    all_indexes = [entry["index"] for entry in first["history"] + second["history"]]
    cursor = second["next_history_before"]
    while cursor is not None:
        page = await service.detail(ADMIN, "qa-read-order", history_before=cursor, history_limit=10)
        all_indexes.extend(entry["index"] for entry in page["history"])
        cursor = page["next_history_before"]
    assert all_indexes == list(range(66, -1, -1))
    empty = await service.detail(ADMIN, "qa-read-order", history_before=0)
    assert empty["history"] == [] and not empty["history_has_more"] and empty["next_history_before"] is None
    assert await snapshot(db) == before


@pytest.mark.parametrize("trail", [None, SECRET, {"raw": SECRET}, 23, [None, 1, {"action": "<b>bad</b>"}]])
@mongo_case
async def test_mongo_malformed_audit_warns_not_crashes(db, trail):
    await seed(db, [order(audit_trail=trail)])
    result = await OrderReadService(db).detail(ADMIN, "qa-read-order")
    assert result["data_warnings"] and SECRET not in json.dumps(result)


@mongo_case
async def test_mongo_detail_revision_multifields_and_critical_corruption_block_actions(db):
    documents = [order(id=f"multi-{index}", order_version=3, **{name: {"raw": SECRET}})
                 for index, name in enumerate(MULTI_FIELDS)]
    documents += [order(id="bad-driver", driver_id={"raw": SECRET}),
                  order(id="bad-status", status={"raw": SECRET}),
                  order(id="bad-revision", order_version={"raw": SECRET})]
    await seed(db, documents)
    service = OrderReadService(db)
    for index, name in enumerate(MULTI_FIELDS):
        result = await service.detail(ADMIN, f"multi-{index}")
        assert name in result["order"] and result["order"][name] is None
        assert result["order"]["read_actions_unavailable"]
        assert "ORDER_ASSIGNMENT_UNSUPPORTED" in result["data_warnings"] and SECRET not in json.dumps(result)
    for name in ("bad-driver", "bad-status", "bad-revision"):
        result = await service.detail(ADMIN, name)
        assert result["order"]["read_actions_unavailable"] and SECRET not in json.dumps(result)


@mongo_case
async def test_mongo_http_real_aggregation_owned_detail_list_and_foreign_guard(db, routes):
    await seed(db, [order(audit_trail=[{"action": "order.created", "created_at": NOW}])])
    for actor in (ADMIN, RESTAURANT, DRIVER):
        for path in ("/read/page", "/read/detail/qa-read-order"):
            response = await http(routes, db, path, actor)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    response = await http(routes, db, "/read/detail/qa-read-order", FOREIGN)
    assert response.status_code == 404
    response = await http(routes, db, "/read/page", headers={"X-Expected-Actor-ID": "other"})
    assert response.status_code == 403


@mongo_case
async def test_mongo_duplicate_business_id_detail_refuses_ambiguity_and_invalid_dates(db):
    await seed(db, [order(created_at="bad"), order(created_at=None)])
    service = OrderReadService(db)
    with pytest.raises(HTTPException) as caught:
        await service.detail(ADMIN, "qa-read-order")
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "ORDER_ID_AMBIGUOUS"
    await db.orders.delete_one({"created_at": None})
    result = await service.detail(ADMIN, "qa-read-order")
    assert result["order"]["created_at"] is None and "ORDER_DATE_UNAVAILABLE" in result["data_warnings"]


@mongo_case
async def test_mongo_scope_requires_scalar_exact_ownership_not_array_membership(db):
    await seed(db, [order(id="array-restaurant", restaurant_id=[RESTAURANT["restaurant_id"], FOREIGN["restaurant_id"]]),
                    order(id="array-driver", driver_id=["qa-read-driver", "other"]), order()])
    service = OrderReadService(db)
    assert "array-restaurant" not in {item["id"] for item in (await service.page(RESTAURANT))["items"]}
    assert "array-driver" not in {item["id"] for item in (await service.page(DRIVER))["items"]}
    for actor, target in ((RESTAURANT, "array-restaurant"), (DRIVER, "array-driver")):
        with pytest.raises(HTTPException) as caught:
            await service.detail(actor, target)
        assert caught.value.status_code == 404
    await db.users.update_one({"id": DRIVER["id"]}, {"$set": {"id": [DRIVER["id"], "foreign"]}})
    with pytest.raises(HTTPException) as caught:
        await service.page(DRIVER)
    assert caught.value.status_code == 403


@mongo_case
async def test_mongo_microsecond_utc_bounds_apply_to_normalized_millisecond_dates(db):
    await seed(db, [order(id="zero", created_at="2026-10-08T10:00:00.000Z"),
                    order(id="one", created_at="2026-10-08T10:00:00.001Z"),
                    order(id="two", created_at="2026-10-08T10:00:00.002Z")])
    result = await OrderReadService(db).page(ADMIN, from_date="2026-10-08T10:00:00.000001Z",
                                          to_date="2026-10-08T10:00:00.001001Z")
    assert [item["id"] for item in result["items"]] == ["one"]


@pytest.fixture
def real_auth_routes(monkeypatch):
    root = Path(r"C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend")
    spec = importlib.util.spec_from_file_location("_pd_s206_real_auth", root / "auth.py")
    auth = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, auth)
    spec.loader.exec_module(auth)
    # Synthetic signing material only; never read JWT_SECRET or credentials.
    monkeypatch.setattr(auth, "get_jwt_secret", lambda: "qa-s206-synthetic-signing-material-not-a-real-credential")
    monkeypatch.setitem(sys.modules, "auth", auth)
    path = Path(__file__).resolve().parents[1] / "routers/orders.py"
    spec = importlib.util.spec_from_file_location("_pd_s206_real_auth_orders", path)
    routes = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, routes)
    spec.loader.exec_module(routes)
    return routes, auth


async def authenticated_http(pair, database, actor=ADMIN, *, cookie_actor=None, expected=None, path="/read/page", token=None):
    routes, auth = pair
    routes.db = auth.db = database
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    def access(user):
        return auth.create_access_token({**user, "email": user["id"] + "@synthetic.invalid", "name": "QA User"})
    headers = {"Authorization": "Bearer " + (token if token is not None else access(actor)),
               "X-Expected-Actor-ID": expected or actor["id"]}
    if cookie_actor is not None:
        headers["Cookie"] = "access_token=" + (access(cookie_actor) if isinstance(cookie_actor, dict) else cookie_actor)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
        return await client.get("/api/orders" + path, headers=headers)


@mongo_case
async def test_mongo_auth_real_jwt_cookie_first_bearer_no_dependency_overrides(db, real_auth_routes):
    await seed(db, [order(), order(id="qa-foreign-order", restaurant_id=FOREIGN["restaurant_id"], driver_id="other")])
    for actor in (ADMIN, RESTAURANT, DRIVER):
        for path in ("/read/page", "/read/detail/qa-read-order"):
            response = await authenticated_http(real_auth_routes, db, actor, path=path)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    response = await authenticated_http(real_auth_routes, db, ADMIN, cookie_actor=DRIVER)
    assert response.status_code == 403 and response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
    response = await authenticated_http(real_auth_routes, db, ADMIN, cookie_actor=DRIVER, expected=DRIVER["id"])
    assert response.status_code == 200 and [item["id"] for item in response.json()["items"]] == ["qa-read-order"]
    for kwargs in ({"token": "malformed.jwt"}, {"cookie_actor": "malformed.jwt"}):
        response = await authenticated_http(real_auth_routes, db, **kwargs)
        assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    response = await authenticated_http(real_auth_routes, db, FOREIGN, path="/read/detail/qa-read-order")
    assert response.status_code == 404


@mongo_case
async def test_mongo_auth_actual_disabled_current_role_and_link_changes(db, real_auth_routes):
    await seed(db, [order(), order(id="qa-new-driver-order", driver_id="qa-new-driver")])
    # JWT actor claims do not grant the prior role after a DB role change.
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"role": "restaurant", "restaurant_id": "qa-empty"}})
    response = await authenticated_http(real_auth_routes, db)
    assert response.status_code == 200 and response.json()["items"] == []
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"account_disabled": True}})
    response = await authenticated_http(real_auth_routes, db)
    assert response.status_code == 403
    await db.drivers.update_one({"user_id": DRIVER["id"]}, {"$set": {"id": "qa-new-driver"}})
    response = await authenticated_http(real_auth_routes, db, DRIVER)
    assert response.status_code == 200 and [item["id"] for item in response.json()["items"]] == ["qa-new-driver-order"]
    await db.users.update_one({"id": DRIVER["id"]}, {"$set": {"driver_id": "qa-read-driver"}})
    response = await authenticated_http(real_auth_routes, db, DRIVER)
    assert response.status_code == 403
    await db.users.update_one({"id": DRIVER["id"]}, {"$unset": {"driver_id": ""}})
    await db.drivers.update_one({"user_id": DRIVER["id"]}, {"$set": {"account_disabled": True}})
    response = await authenticated_http(real_auth_routes, db, DRIVER)
    assert response.status_code == 403
    await db.users.update_one({"id": FOREIGN["id"]}, {"$set": {"role": "unsupported"}})
    response = await authenticated_http(real_auth_routes, db, FOREIGN)
    assert response.status_code == 403


PK_CASES = ["ascii" * 24, "\u00e9" * 86, "\u00e9" * 120, "\U0001f600" * 120,
            "\x01" * 120, ObjectId("ffffffffffffffffffffffff"), 12, Int64(1 << 40)]


@pytest.mark.parametrize("pk", PK_CASES)
def test_review_r1_compact_cursor_unicode_control_and_bson_roundtrip(pk):
    document = projected(order(_id=pk, id="\U0001f600" * 120))
    binding = "qa-binding"
    cursor = reads._encode_cursor(document, binding)
    assert len(cursor.encode("ascii")) <= reads.MAX_CURSOR_LENGTH == 4096
    date, identifier, decoded_pk = reads._decode_cursor(cursor, binding)
    assert date == NOW and identifier == document["id"] and decoded_pk == pk


@pytest.mark.parametrize("pk", PK_CASES)
@mongo_case
async def test_mongo_review_r1_unicode_pk_boundary_cursor_two_pages(db, pk):
    lesser_pk = ObjectId("000000000000000000000000") if isinstance(pk, ObjectId) else 1 if isinstance(pk, int) else ""
    await seed(db, [order(_id=pk, id=[], order_number="boundary"),
                    order(_id=lesser_pk, id={}, order_number="after")])
    service = OrderReadService(db)
    first = await service.page(ADMIN, limit=1)
    assert first["items"][0]["order_number"] == "boundary" and first["has_more"]
    assert len(first["next_cursor"].encode("ascii")) <= 4096
    second = await service.page(ADMIN, limit=1, cursor=first["next_cursor"])
    assert second["items"][0]["order_number"] == "after" and not second["has_more"]
    assert second["next_cursor"] is None


@mongo_case
async def test_mongo_review_r1_both_unicode_business_id_and_pk_at_boundary(db):
    await seed(db, [order(_id="\U0001f600" * 120, id="\U0001f600" * 120, order_number="first"),
                    order(_id="other", id="a", order_number="last")])
    service = OrderReadService(db)
    first = await service.page(ADMIN, limit=1)
    second = await service.page(ADMIN, limit=1, cursor=first["next_cursor"])
    assert [first["items"][0]["order_number"], second["items"][0]["order_number"]] == ["first", "last"]


@mongo_case
async def test_mongo_review_r3_rejected_changes_absent_only_real_null_preserved(db):
    audit = {"action": "order.ready", "created_at": NOW, "changes": {
        "customer_name": None, "notes": "QA safe note", "customer_address": {"raw": SECRET},
        "customer_phone": [SECRET], "driver_name": "x" * 1001,
        "from_preparation_status": "PREPARING", "to_preparation_status": "READY",
    }}
    await seed(db, [order(audit_trail=[audit])])
    result = await OrderReadService(db).detail(ADMIN, "qa-read-order")
    changes = result["history"][0]["changes"]
    assert changes == {"customer_name": None, "notes": "QA safe note",
                       "from_preparation_status": "PREPARING", "to_preparation_status": "READY"}
    assert "HISTORY_FIELD_INVALID" in result["data_warnings"] and SECRET not in json.dumps(result)


@pytest.mark.parametrize("value", ["sNaN", "NaN", "Infinity", "-Infinity", "1E+6144", "-1E+6144"])
def test_review_r4_decimal_nonfinite_extreme_is_unavailable_not_exception(value):
    document = order(total_amount=Decimal128(value), items=[{"name": "QA Item", "quantity": 1, "price": Decimal128(value)}])
    warnings = set()
    result = safe_order(document, warnings)
    assert result["total_amount"] is None and result["items"][0]["price"] is None
    assert "ORDER_FIELD_INVALID" in warnings


@pytest.mark.parametrize("value,expected", [("0", 0.0), ("1000000", 1000000.0), ("32.50", 32.5)])
def test_review_r4_finite_decimal_boundary_and_integer_strictness(value, expected):
    assert reads._number(Decimal128(value), 0, 1000000) == expected
    assert reads._number(Decimal128("0"), 0, reads.MAX_ORDER_VERSION, integral=True) is None


@mongo_case
async def test_mongo_review_r4_decimal_adversarial_page_and_detail_remain_200(db, routes):
    values = ["sNaN", "NaN", "Infinity", "-Infinity", "1E+6144", "-1E+6144", "32.50"]
    await seed(db, [order(id=f"decimal-{index}", total_amount=Decimal128(value),
                         items=[{"name": "QA Item", "quantity": 1, "price": Decimal128(value)}])
                    for index, value in enumerate(values)])
    response = await http(routes, db, "/read/page?view=all")
    assert response.status_code == 200 and "ORDER_FIELD_INVALID" in response.json()["data_warnings"]
    for index, value in enumerate(values):
        response = await http(routes, db, f"/read/detail/decimal-{index}")
        assert response.status_code == 200
        result = response.json()
        assert result["order"]["total_amount"] == (32.5 if value == "32.50" else None)
        assert result["order"]["items"][0]["price"] == (32.5 if value == "32.50" else None)


@pytest.mark.parametrize("changes", [{"preparation_status": "BROKEN"}, {"preparation_started_at": "bad"},
    {"preparation_due_at": True}, {"preparation_ready_at": "bad"}, {"accepted_at": "bad"},
    {"assigned_at": []}, {"picked_up_at": "bad"}, {"delivered_at": "bad"}, {"cancelled_at": "bad"},
    {"driver_id": " "}, {"preparation_time": 0}, {"customer_latitude": 12.5}])
def test_review_r5_critical_semantic_invalid_is_read_only(changes):
    warnings = set()
    result = safe_order(order(order_version=3, **changes), warnings)
    assert result["read_actions_unavailable"] and "ORDER_FIELD_INVALID" in warnings


@mongo_case
async def test_mongo_review_r5_bounded_datetime_decode_and_semantic_action_blocker(db):
    invalid_dates = [DatetimeMS(-62135596800001), DatetimeMS(253402300800000)]
    documents = [order(id="bad-prep", order_version=3, preparation_status="BROKEN"),
                 order(id="bad-driver", order_version=3, driver_id=" "),
                 order(id="bad-timer", order_version=3, preparation_time=0),
                 order(id="valid", order_version=3, driver_id=None, driver_name=None)]
    for index, value in enumerate(invalid_dates):
        documents += [order(id=f"date-{index}", order_version=3, preparation_started_at=value,
                            accepted_at=value, updated_at=value, audit_trail=[{"action": "order.ready", "created_at": value}])]
    await seed(db, documents)
    service = OrderReadService(db)
    page = await service.page(ADMIN)
    for document in page["items"]:
        assert document["read_actions_unavailable"] is (document["id"] != "valid")
    for index in range(2):
        result = await service.detail(ADMIN, f"date-{index}")
        assert result["order"]["read_actions_unavailable"]
        assert result["order"]["preparation_started_at"] is None and result["order"]["accepted_at"] is None
        assert result["history"][0]["created_at"] is None
        assert "HISTORY_DATE_UNAVAILABLE" in result["data_warnings"]


@pytest.mark.parametrize("status", ["NEW", "PREPARING", "READY"])
@mongo_case
async def test_mongo_review_r6_preparation_presence_writer_parity_and_legacy_null(db, status):
    from models.order_mutation import EditOrderCommand
    from utils.order_editing import OrderEditingService, EditingError

    variants = [order(id="absent", status=status, order_version=3, driver_id=None, driver_name=None),
                order(id="null", status=status, order_version=3, driver_id=None, driver_name=None, preparation_status=None),
                order(id="matching", status=status, order_version=3, driver_id=None, driver_name=None, preparation_status=status),
                order(id="mismatch", status=status, order_version=3, driver_id=None, driver_name=None,
                      preparation_status="READY" if status != "READY" else "NEW"),
                order(id="legacy-null", status=status, driver_id=None, driver_name=None, preparation_status=None)]
    await seed(db, variants)
    service = OrderReadService(db)
    page = await service.page(ADMIN)
    for document in page["items"]:
        if document["id"] == "absent":
            assert "preparation_status" not in document and not document["read_actions_unavailable"]
        if document["id"] == "legacy-null":
            assert "preparation_status" in document and document["preparation_status"] is None
            assert "order_version" not in document and not document["read_actions_unavailable"]
    command = EditOrderCommand(client_operation_id="qa_s206_edit_compare", expected_order_version=3, changes={"notes": "QA changed"})
    operation = {"restaurant_id": RESTAURANT["restaurant_id"]}
    for raw in variants[:4]:
        result = await service.detail(ADMIN, raw["id"])
        clean = result["order"]
        valid = raw["id"] in ("absent", "matching")
        assert clean["read_actions_unavailable"] is (not valid)
        assert ("preparation_status" in clean) is ("preparation_status" in raw)
        for document in (raw, clean):
            if valid:
                assert OrderEditingService._changes(operation, command, document) == {"notes": "QA changed"}
            else:
                with pytest.raises(EditingError):
                    OrderEditingService._changes(operation, command, document)


def test_review_r9_encoded_slash_detail_reaches_real_asgi_and_preserves_id(routes):
    order_id = "id/with?query#fragment%\U0001f600"
    document = detail_document(order(id=order_id), [{"index": 0, "action": "order.created", "created_at": NOW}])
    database = fake_db(RESTAURANT, [document])
    auth_calls = []

    async def authenticated(*args):
        auth_calls.append(True)
        return RESTAURANT

    routes.get_current_user = authenticated
    path = "/read/detail/" + quote(order_id, safe="") + "?history_before=1&history_limit=1"
    response = asyncio.run(http(routes, database, path, actor=None,
                               headers={"X-Expected-Actor-ID": RESTAURANT["id"]}))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store" and auth_calls == [True]
    assert response.json()["order"]["id"] == order_id
    assert response.json()["history"][0]["action"] == "order.created"
    query = database.orders.calls[0][0][0]["$match"]
    assert query["id"] == order_id and query["restaurant_id"] == RESTAURANT["restaurant_id"]


R9_VALID_IDS = [
    pytest.param("a" * 120, id="ascii-120"),
    pytest.param("id/with?query#fragment%\U0001f600", id="slash-query-hash-percent"),
    pytest.param("id/%2F%3F%23%25", id="literal-percent-escapes"),
    pytest.param("id//nested/end/", id="multiple-trailing-slashes"),
    pytest.param("/id-leading", id="leading-slash"),
    pytest.param("id/../literal", id="literal-dot-segments"),
    pytest.param("\U0001f600" * 120, id="supplementary-120"),
    pytest.param("a" * 115 + "/?%#\U0001f600", id="mixed-reserved-unicode-120"),
    pytest.param("id/ \u00e9 \u4e2d?query#fragment%", id="internal-space-bmp"),
]


@pytest.mark.parametrize("order_id", R9_VALID_IDS)
def test_review_r9_real_asgi_exact_encoded_identity_and_history_query(routes, order_id):
    document = detail_document(order(id=order_id), [{"index": 0, "action": "order.created", "created_at": NOW}])
    database = fake_db(documents=[document])
    response = asyncio.run(http(routes, database, "/read/detail/" + quote(order_id, safe=""),
                               params={"history_before": "1", "history_limit": "1"}))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["order"]["id"] == order_id
    pipeline = database.orders.calls[0][0]
    assert pipeline[0]["$match"]["id"] == order_id
    assert pipeline[-1]["$project"]["_history_end"]["$min"][0] == 1
    assert pipeline[-1]["$project"]["_history_start"]["$max"][1]["$subtract"][1] == 1


@pytest.mark.parametrize("order_id", ["", "a" * 121, "\U0001f600" * 121, " bad/id", "bad/id ",
                                     "bad/\x00id", "bad/\x1fid", "bad/\x7fid"])
def test_review_r9_real_asgi_invalid_id_rejected_before_business_read(routes, order_id):
    database = fake_db()
    response = asyncio.run(http(routes, database, "/read/detail/" + quote(order_id, safe="")))
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert not database.users.calls and not database.orders.calls


@pytest.mark.parametrize("case,status", [("unauthenticated", 401), ("switched-actor", 403), ("invalid-query", 422)])
def test_review_r9_real_asgi_slash_auth_actor_and_query_guards(routes, case, status):
    database = fake_db()
    path = "/read/detail/" + quote("id/with?query#fragment%", safe="")
    kwargs = {"actor": None} if case == "unauthenticated" else {"headers": {"X-Expected-Actor-ID": "other"}} if case == "switched-actor" else {"params": {"force": "1"}}
    response = asyncio.run(http(routes, database, path, **kwargs))
    assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert not database.orders.calls


@pytest.mark.parametrize("method,path,expected", [
    ("GET", "/orders/read/page", "/orders/read/page"),
    ("GET", "/orders/read/detail/id/path", "/orders/read/detail/{order_id:path}"),
    ("GET", "/orders/read/detail/id/path/assign", "/orders/read/detail/{order_id:path}"),
    ("GET", "/orders/qa-order", "/orders/{order_id}"),
    ("GET", "/orders/driver/qa-driver", "/orders/driver/{driver_id}"),
    ("GET", "/orders/restaurant/qa-restaurant", "/orders/restaurant/{restaurant_id}"),
    ("GET", "/orders/restaurant/qa-restaurant/prep-availability", "/orders/restaurant/{restaurant_id}/prep-availability"),
    ("POST", "/orders", "/orders"),
    ("PUT", "/orders/qa-order/assign", "/orders/{order_id}/assign"),
    ("PUT", "/orders/qa-order/preparing", "/orders/{order_id}/preparing"),
    ("PUT", "/orders/qa-order/ready", "/orders/{order_id}/ready"),
    ("PUT", "/orders/qa-order/status", "/orders/{order_id}/status"),
    ("POST", "/orders/qa-order/problem", "/orders/{order_id}/problem"),
])
def test_review_r9_only_new_detail_route_captures_suffix_legacy_dispatch_unchanged(routes, method, path, expected):
    from starlette.routing import Match

    scope = {"type": "http", "method": method, "path": path, "root_path": ""}
    matched = next(route for route in routes.router.routes if route.matches(scope)[0] == Match.FULL)
    assert matched.path == expected


@pytest.mark.parametrize("order_id", R9_VALID_IDS)
@mongo_case
async def test_mongo_review_r9_encoded_detail_real_jwt_exact_id_tenant_and_history(db, real_auth_routes, order_id):
    entries = [{"id": f"audit-{index}", "action": "order.created", "created_at": NOW,
                "performed_by": ADMIN["id"], "performed_by_role": "admin"} for index in range(4)]
    foreign_id = order_id[:-1] + ("y" if order_id[-1] == "x" else "x")
    await seed(db, [order(id=order_id, audit_trail=entries),
                    order(id=foreign_id, restaurant_id=FOREIGN["restaurant_id"], driver_id="other")])
    path = "/read/detail/" + quote(order_id, safe="") + "?history_before=3&history_limit=2"
    before = await snapshot(db)
    for actor in (ADMIN, RESTAURANT, DRIVER):
        response = await authenticated_http(real_auth_routes, db, actor, path=path)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["order"]["id"] == order_id
        assert [entry["index"] for entry in payload["history"]] == [2, 1]
        assert payload["next_history_before"] == 1 and payload["history_has_more"]
        older = await authenticated_http(real_auth_routes, db, actor,
            path="/read/detail/" + quote(order_id, safe="") + "?history_before=1&history_limit=2")
        assert older.status_code == 200
        assert [entry["index"] for entry in older.json()["history"]] == [0]
        assert older.json()["next_history_before"] is None and not older.json()["history_has_more"]
    response = await authenticated_http(real_auth_routes, db, FOREIGN, path=path)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "ORDER_NOT_FOUND"
    response = await authenticated_http(real_auth_routes, db, RESTAURANT, expected=FOREIGN["id"], path=path)
    assert response.status_code == 403 and response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
    assert await snapshot(db) == before
