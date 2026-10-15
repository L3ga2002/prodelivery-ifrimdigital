"""F1 owner oracles; synthetic bounded collections, never a database connection."""

import asyncio
from copy import deepcopy
import json

from bson import BSON
from pydantic import ValidationError
import pytest

from models.order_finance_preview import CreateFinancePreview, RemakeFinancePreview
from utils.order_creation import CreationError
from utils.order_finance_preview import OrderFinancePreviewService
from utils.order_finance import quote_at_admission
from models.order_mutation import CreateOrderCommand


KEY = b"synthetic-only-finance-preview-test-key"
ADMIN = {"id": "synthetic-admin", "role": "admin"}
RESTAURANT = {"id": "synthetic-restaurant-user", "role": "restaurant", "restaurant_id": "r1"}
DRIVER = {"id": "synthetic-driver", "role": "driver"}
PII = ("Customer Private Sentinel", "0700099011", "Private Address Sentinel", "Private Note Sentinel")


def create_request(payment="CASH", products=3250, **financial):
    return CreateFinancePreview(order={"restaurant_id": "r1", "customer_name": PII[0],
        "customer_phone": PII[1], "customer_address": PII[2], "notes": PII[3],
        "customer_latitude": 1.0, "customer_longitude": 1.0,
        "total_amount": products / 100, "payment_type": payment,
        "items": [{"name": "Synthetic Item", "quantity": 1, "price": products / 100}]},
        financial={"tariff_version": "v1", "products_bani": products, "basis": "zone", "zone_id": "z1", **financial})


def remake_request(payment="CASH", products=3250, **changes):
    return RemakeFinancePreview(**{"expected_order_version": 4, "problem_type": "missing_product",
        "description": "Synthetic replacement", "items": [{"name": "Synthetic Item", "quantity": 1, "unit_price_bani": products}],
        "payment_type": payment, "collection_basis": "new_receipt" if payment == "CASH" else "prepaid_new_order",
        "client_collection_bani": products if payment == "CASH" else 0,
        "advance_required_bani": products if payment == "CASH" else 0,
        "financial": create_request(payment, products).financial.model_dump(mode="python"), **changes})


def tariff(**changes):
    return {"contract_version": 1, "restaurant_id": "r1", "version": "v1", "currency": "RON", "approved": True,
        "zones": {"z1": {"restaurant_transport_bani": 1600, "courier_remuneration_bani": 975}}, **changes}


def zone(**changes):
    return {"id": "z1", "restaurant_id": "r1", "is_active": True, "name": "Synthetic Zone",
        "sector": "Synthetic", "zone_level": 1,
        "polygon": [{"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 2.0},
                    {"lat": 2.0, "lng": 2.0}, {"lat": 2.0, "lng": 0.0}], **changes}


def parent(**changes):
    return {"id": "parent", "restaurant_id": "r1", "order_version": 4, "status": "DELIVERED",
        "source": "S", "customer_name": PII[0], "customer_phone": PII[1], "customer_address": PII[2],
        "customer_latitude": 1.0, "customer_longitude": 1.0, "items": [], "payment_type": "CARD", **changes}


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, maximum):
        return deepcopy(self.rows[:maximum])


class Collection:
    def __init__(self, database, name):
        self.db, self.name = database, name

    def aggregate(self, pipeline, maxTimeMS):
        assert maxTimeMS == 2000
        assert len(pipeline) == 3 and "$match" in pipeline[0] and "$limit" in pipeline[1]
        query, maximum = pipeline[0]["$match"], pipeline[1]["$limit"]
        assert 1 <= maximum <= 301
        assert pipeline[2]["$project"]["document"]["$cond"][0]["$lte"][0] == {"$bsonSize": "$$ROOT"}
        size = pipeline[2]["$project"]["document"]["$cond"][0]["$lte"][1]
        assert size <= 131072
        self.db.reads.append((self.name, deepcopy(query), maximum))
        def match(doc):
            return all(doc.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value
                       else doc.get(key) == value for key, value in query.items())
        rows = [doc for doc in self.db.rows.get(self.name, []) if match(doc)][:maximum]
        return Cursor([{"document": doc if len(BSON.encode(doc)) <= size else None} for doc in rows])

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected collection method {self.name}.{name}; preview must only aggregate reads")


class Database:
    def __init__(self):
        self.rows = {"users": [ADMIN.copy(), RESTAURANT.copy(), DRIVER.copy()],
            "restaurants": [{"id": "r1", "name": "Synthetic Restaurant", "is_active": True}],
            "orders": [parent()], "restaurant_tariff_versions": [tariff()], "delivery_zones": [zone()],
            "order_operation_settings": [{"_id": f"order-{name}-v1", "enabled": True} for name in ("finance", "create", "remake")]}
        self.reads = []

    def get_collection(self, name):
        return Collection(self, name)

    def __getattr__(self, name):
        raise AssertionError(f"No direct database interface {name}")


def run(awaitable):
    return asyncio.run(awaitable)


def service(db=None, key=KEY):
    return OrderFinancePreviewService(db or Database(), signing_key=key)


def failure(awaitable, code=None, status=None):
    with pytest.raises(CreationError) as caught:
        run(awaitable)
    if code:
        assert caught.value.code == code
    if status:
        assert caught.value.status_code == status
    assert all(value not in str(caught.value) for value in PII)


@pytest.mark.parametrize("payment,products,collection", [("CASH", 3250, 3250), ("CARD", 3250, 0), ("CASH", 0, 0)])
def test_create_readonly_quote_is_l3_and_never_payment(payment, products, collection):
    db = Database(); before = deepcopy(db.rows)
    result = run(service(db).quote_create(create_request(payment, products), ADMIN))
    assert db.rows == before
    assert result["products_bani"] == products and result["client_collection_bani"] == collection
    assert result["advance_required_bani"] == collection
    assert result["restaurant_transport_bani"] == 1600 and result["courier_remuneration_bani"] == 975
    assert result["informational"] is True
    assert result["advance_paid_bani"] is result["refund_due_bani"] is result["refund_paid_bani"] is None
    assert not {"snapshot_digest", "snapshot_at", "operation_ref", "tariff_rule"} & result.keys()
    assert all(value not in json.dumps(result) for value in PII)
    assert not {"order_operations", "audit_logs", "counters"} & {read[0] for read in db.reads}


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
@pytest.mark.parametrize("payment,products", [("CASH", 3250), ("CARD", 3250), ("CASH", 0)])
def test_remake_uses_explicit_new_receipt_and_private_projection(actor, payment, products):
    db = Database(); before = deepcopy(db.rows)
    result = run(service(db).quote_remake("parent", remake_request(payment, products), actor))
    assert db.rows == before
    assert result["parent_order_id"] == "parent" and result["parent_order_version"] == 4
    assert result["client_collection_bani"] == (products if payment == "CASH" else 0)
    assert ("courier_remuneration_bani" in result) == (actor["role"] == "admin")
    assert "tariff_rule" not in result and "snapshot_digest" not in result
    assert all(value not in json.dumps(result) for value in PII)


def test_capabilities_and_legacy_admin_only_remain_separate():
    db = Database()
    result = run(service(db).capabilities("r1", RESTAURANT))
    assert result["create_quote_enabled"] is False and result["remake_quote_enabled"] is True
    db.rows["order_operation_settings"][1]["enabled"] = False
    assert run(service(db).capabilities("r1", ADMIN))["create_quote_enabled"] is False
    assert run(service(db).quote_remake("parent", remake_request(), RESTAURANT))["kind"] == "remake"
    failure(service(db).quote_create(create_request(), ADMIN), "FINANCIAL_CREATE_NOT_ENABLED")
    failure(service(db).quote_create(create_request(), RESTAURANT), "NOT_AUTHORIZED", 403)


@pytest.mark.parametrize("flag", ["finance", "create", "remake"])
@pytest.mark.parametrize("value", ["true", 1, None, {}])
def test_corrupt_marker_is_unavailable_not_disabled(flag, value):
    db = Database()
    next(row for row in db.rows["order_operation_settings"] if row["_id"] == f"order-{flag}-v1")["enabled"] = value
    failure(service(db).capabilities("r1", ADMIN), "CAPABILITIES_INVALID", 503)


def test_missing_finance_marker_is_disabled_but_discovery_refuses():
    db = Database(); db.rows["order_operation_settings"] = []
    assert run(service(db).capabilities("r1", ADMIN))["finance_enabled"] is False
    failure(service(db).tariffs("r1", ADMIN), "FINANCIAL_NOT_ENABLED", 503)


@pytest.mark.parametrize("actor", [DRIVER, {**RESTAURANT, "restaurant_id": "foreign"}, {**ADMIN, "role": "restaurant"}])
def test_unauthorized_actor_never_reads_tariffs(actor):
    db = Database()
    failure(service(db).tariffs("r1", actor), status=403)
    assert not any(name == "restaurant_tariff_versions" for name, *_ in db.reads)


@pytest.mark.parametrize("target,change", [("users", {"account_disabled": True}), ("restaurants", {"is_active": False}),
    ("restaurants", {"accepting_orders": False}), ("restaurants", {"account_disabled": True})])
def test_inactive_scope_refuses(target, change):
    db = Database(); db.rows[target][0].update(change)
    failure(service(db).quote_create(create_request(), ADMIN))


def test_foreign_and_missing_parent_are_indistinguishable_and_scoped():
    db = Database(); db.rows["orders"][0]["restaurant_id"] = "foreign"
    for parent_id in ("parent", "absent"):
        failure(service(db).quote_remake(parent_id, remake_request(), RESTAURANT), "ORDER_NOT_FOUND", 404)
    assert all(query.get("restaurant_id") == "r1" for name, query, _ in db.reads if name == "orders")


def test_tariffs_are_complete_metadata_without_prices_or_foreign_substitution():
    db = Database()
    db.rows["restaurant_tariff_versions"] += [tariff(version="v2"), tariff(version="draft", approved=False), tariff(restaurant_id="foreign")]
    result = run(service(db).tariffs("r1", RESTAURANT))
    assert result["tariffs"] == [{"version": name, "currency": "RON", "zone_ids": ["z1"]} for name in ("v1", "v2")]
    assert not any(token in json.dumps(result) for token in ("975", "1600", "foreign", "tariff_rule"))
    db.rows["restaurant_tariff_versions"] = [tariff(restaurant_id="foreign")]
    failure(service(db).quote_create(create_request(), ADMIN), "FINANCIAL_GRID_UNAVAILABLE")


@pytest.mark.parametrize("case", ["duplicate", "unapproved_collision", "corrupt", "currency", "incomplete", "too_many", "oversize"])
def test_tariff_failclosed(case):
    db = Database()
    if case == "duplicate": db.rows["restaurant_tariff_versions"].append(tariff())
    if case == "unapproved_collision": db.rows["restaurant_tariff_versions"].append(tariff(approved=False))
    if case == "corrupt": db.rows["restaurant_tariff_versions"][0]["approved"] = "yes"
    if case == "currency": db.rows["restaurant_tariff_versions"][0]["currency"] = "EUR"
    if case == "incomplete": db.rows["restaurant_tariff_versions"][0]["zones"]["z1"].pop("courier_remuneration_bani")
    if case == "too_many": db.rows["restaurant_tariff_versions"] = [tariff(version=f"v{i}") for i in range(51)]
    if case == "oversize": db.rows["restaurant_tariff_versions"][0]["unexpected"] = "x" * 131072
    failure(service(db).tariffs("r1", ADMIN))
    failure(service(db).quote_create(create_request(), ADMIN))


def test_explicit_zero_grid_valid_and_missing_version_is_not_latest():
    db = Database(); db.rows["restaurant_tariff_versions"] = [tariff(zones={"z1": {"restaurant_transport_bani": 0, "courier_remuneration_bani": 0}})]
    result = run(service(db).quote_create(create_request(), ADMIN))
    assert result["restaurant_transport_bani"] == result["courier_remuneration_bani"] == 0
    failure(service(db).quote_create(create_request(tariff_version="missing"), ADMIN), "FINANCIAL_GRID_UNAVAILABLE")


@pytest.mark.parametrize("case", ["missing", "limit", "duplicate", "short", "coords", "nan", "self_crossing", "metadata", "oversize"])
def test_zone_failclosed(case):
    db = Database(); value = db.rows["delivery_zones"][0]
    if case == "missing": db.rows["delivery_zones"] = []
    if case == "limit": db.rows["delivery_zones"] = [zone(id=f"z{i}") for i in range(301)]
    if case == "duplicate": db.rows["delivery_zones"].append(zone())
    if case == "short": value["polygon"] = []
    if case == "coords": value["polygon"][0]["lat"] = True
    if case == "nan": value["polygon"][0]["lat"] = float("nan")
    if case == "self_crossing": value["polygon"][1], value["polygon"][2] = value["polygon"][2], value["polygon"][1]
    if case == "metadata": value["name"] = " invalid "
    if case == "oversize": value["unrelated"] = "x" * 65536
    failure(service(db).quote_create(create_request(), ADMIN))


def test_outside_explicitly_unavailable_and_zone_mismatch_not_zero():
    failure(service().quote_create(create_request(basis="outside", zone_id=None, route_distance_m=5000,
        distance_evidence_ref="synthetic-proof"), ADMIN), "FINANCIAL_PREVIEW_OUTSIDE_UNAVAILABLE")
    failure(service().quote_create(create_request(zone_id="foreign"), ADMIN), "FINANCIAL_ZONE_MISMATCH")


@pytest.mark.parametrize("change,code", [({"status": "PICKED_UP"}, "REMAKE_REQUIRES_DELIVERED"),
    ({"order_version": 5}, "ORDER_VERSION_CONFLICT"), ({"has_problem_followup": True}, "REMAKE_ALREADY_EXISTS"),
    ({"custody_contract_version": 1}, "ORDER_DATA_INVALID"), ({"financial_contract_version": 1}, "FINANCIAL_SNAPSHOT_INVALID")])
def test_ineligible_parent_fails_existing_l5a_rules(change, code):
    db = Database(); db.rows["orders"][0].update(change)
    failure(service(db).quote_remake("parent", remake_request(), RESTAURANT), code)


def test_new_receipt_policy_and_client_tariff_rejected():
    failure(service().quote_remake("parent", remake_request(client_collection_bani=0), RESTAURANT), "FINANCIAL_REMAKE_POLICY_REQUIRED")
    command = create_request().model_dump(mode="python"); command["order"]["delivery_fee"] = 0.0
    failure(service().quote_create(CreateFinancePreview(**command), ADMIN), "FINANCIAL_CLIENT_TARIFF_FORBIDDEN")


def test_fingerprint_stable_across_instances_and_sensitive_to_all_relevant_basis():
    db = Database()
    original = run(service(db).quote_create(create_request(), ADMIN))["quote_fingerprint"]
    assert run(service(db).quote_create(create_request(), ADMIN))["quote_fingerprint"] == original
    assert run(service(db, b"second-synthetic-key").quote_create(create_request(), ADMIN))["quote_fingerprint"] != original
    for path, value in (("notes", "New note"), ("customer_latitude", 1.1), ("payment_type", "CARD")):
        request = create_request().model_dump(mode="python"); request["order"][path] = value
        assert run(service(db).quote_create(CreateFinancePreview(**request), ADMIN))["quote_fingerprint"] != original
    db.rows["restaurant_tariff_versions"][0]["zones"]["z1"]["courier_remuneration_bani"] += 1
    assert run(service(db).quote_create(create_request(), ADMIN))["quote_fingerprint"] != original
    db = Database(); db.rows["delivery_zones"][0]["polygon"][1]["lng"] = 2.1
    assert run(service(db).quote_create(create_request(), ADMIN))["quote_fingerprint"] != original


@pytest.mark.parametrize("key", [None, b"", b" ", "", 7])
def test_signing_key_must_be_injected_by_server(key):
    failure(service(key=key).quote_create(create_request(), ADMIN), "FINANCIAL_PREVIEW_KEY_UNAVAILABLE", 503)


@pytest.mark.parametrize("value", [True, "3250", -1, 100000001, 3.2, float("nan"), float("inf")])
def test_strict_bani(value):
    with pytest.raises(ValidationError): create_request(products_bani=value)


def test_timeout_is_bounded_and_private(monkeypatch):
    import utils.order_finance_preview as module
    monkeypatch.setattr(module, "DEADLINE_SECONDS", 0.01)
    db = Database()
    async def slow(*args, **kwargs): await asyncio.sleep(1)
    current = service(db); monkeypatch.setattr(current, "_scope", slow)
    failure(current.capabilities("r1", ADMIN), "FINANCIAL_PREVIEW_UNAVAILABLE", 503)


def test_authority_changed_during_quote_is_checked_before_response(monkeypatch):
    db = Database(); current = service(db); original = current._quote
    async def late_change(*args, **kwargs):
        result = await original(*args, **kwargs)
        db.rows["users"][0]["account_disabled"] = True
        return result
    monkeypatch.setattr(current, "_quote", late_change)
    failure(current.quote_create(create_request(), ADMIN), "ACCOUNT_DISABLED", 403)


def test_parent_version_and_actor_bind_fingerprint():
    db = Database()
    first = run(service(db).quote_remake("parent", remake_request(), RESTAURANT))["quote_fingerprint"]
    db.rows["orders"][0]["order_version"] += 1
    second = run(service(db).quote_remake("parent", remake_request(expected_order_version=5), RESTAURANT))["quote_fingerprint"]
    assert first != second
    assert run(service(db).quote_remake("parent", remake_request(expected_order_version=5), ADMIN))["quote_fingerprint"] != second
