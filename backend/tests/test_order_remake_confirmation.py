"""F3A owner probes using synthetic collections; no application or live database."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from bson import BSON
from pydantic import ValidationError
import pytest

from models.order_remakes import CloseFinancialRemake, RemakeCommand
from utils.order_creation import CreationError, VerifiedFinancialContext
from utils.order_finance_preview import OrderFinancePreviewService
from utils.order_remakes import OrderRemakeService, _intent, operation_key
from test_order_finance_confirmation import Database as CreationDatabase, Collection as CreationCollection
from test_order_finance_preview import ADMIN, RESTAURANT, KEY, PII, Cursor, parent, remake_request

OP = "financial_remake_owner_0001"


def context(actor=ADMIN):
    return VerifiedFinancialContext(actor["id"], actor["role"], actor.get("restaurant_id"))


class Collection(CreationCollection):
    async def update_one(self, query, update, session=None):
        self.event("update_one", session)
        def matches(doc):
            for key, value in query.items():
                actual = doc.get(key)
                if isinstance(value, dict):
                    if "$ne" in value and actual == value["$ne"]: return False
                    if "$eq" in value and (type(actual) is not int or actual != value["$eq"]): return False
                    if "$exists" in value and (key in doc) != value["$exists"]: return False
                elif actual != value: return False
            return True
        for doc in self.documents:
            if matches(doc):
                doc.update(deepcopy(update.get("$set", {})))
                for key, value in update.get("$inc", {}).items(): doc[key] = doc.get(key, 0) + value
                for key, value in update.get("$push", {}).items(): doc.setdefault(key, []).append(deepcopy(value))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    def aggregate(self, pipeline, maxTimeMS, session=None):
        assert maxTimeMS == 2000 and len(pipeline) == 3
        self.event("aggregate", session)
        query, maximum = pipeline[0]["$match"], pipeline[1]["$limit"]
        size = pipeline[2]["$project"]["document"]["$cond"][0]["$lte"][1]
        assert 1 <= maximum <= 301 and size <= 131072
        self.db.bounds.append((self.name, deepcopy(query), maximum, size, session))
        def matches(doc):
            return all(doc.get(k) in v["$in"] if isinstance(v, dict) and "$in" in v else doc.get(k) == v for k, v in query.items())
        docs = [doc for doc in self.documents if matches(doc)][:maximum]
        return Cursor([{"document": deepcopy(doc) if len(BSON.encode(doc)) <= size else None} for doc in docs])


class Database(CreationDatabase):
    def __init__(self):
        super().__init__()
        self.bounds = []
        rows = {name: value.documents for name, value in self.collections.items()}
        rows.update(orders=[{"_id": "parent-document", **parent()}], drivers=[], order_custody_events=[], order_incidents=[])
        self.collections = {name: Collection(self, name, docs) for name, docs in rows.items()}


def run(awaitable):
    return asyncio.run(awaitable)


def failure(awaitable, code):
    with pytest.raises(CreationError) as caught:
        run(awaitable)
    assert caught.value.code == code
    assert all(value not in str(caught.value) for value in PII)


async def confirmed(db, actor=ADMIN, payment="CASH", products=3250, operation_id=OP):
    request = remake_request(payment, products)
    quote = await OrderFinancePreviewService(db, signing_key=KEY).quote_remake("parent", request, actor)
    return RemakeCommand(client_operation_id=operation_id, **request.model_dump(mode="python"),
        quote_confirmation={"contract_version": 1, "quote_fingerprint": quote["quote_fingerprint"]})


def close_body(command):
    return CloseFinancialRemake(restaurant_id="r1", expected_order_version=command.expected_order_version,
        quote_confirmation=command.quote_confirmation)


def pending_service(db):
    service = OrderRemakeService(db)
    service.executions = []
    async def execute(key, actor, operation_id, **kwargs):
        service._validated(await service.operations.find_one({"_id": key}), key, actor, **kwargs)
        service.executions.append(key)
        return service._pending(operation_id)
    service._execute = execute
    return service


@pytest.mark.parametrize("payment,products", [("CASH", 3250), ("CARD", 3250), ("CASH", 0), ("CARD", 0)])
def test_v1_omission_and_intent_exact(payment, products):
    from hashlib import sha256
    old = {"client_operation_id": OP, **remake_request(payment, products).model_dump(mode="json")}
    command = RemakeCommand.model_validate(old)
    assert command.model_dump(mode="json") == command.model_dump(mode="python") == old
    assert json.loads(command.model_dump_json()) == old
    canonical = json.dumps({"contract_version": 1, "type": "remake", "parent": "parent",
        "command": {k: v for k, v in old.items() if k != "client_operation_id"}}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    assert _intent("parent", command) == sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize("value", [None, {}, {"contract_version": True, "quote_fingerprint": "a"*64},
    {"contract_version": 1.0, "quote_fingerprint": "a"*64}, {"contract_version": 2, "quote_fingerprint": "a"*64},
    {"contract_version": 1, "quote_fingerprint": "A"*64}, {"contract_version": 1, "quote_fingerprint": "a"*63},
    {"contract_version": 1, "quote_fingerprint": "a"*64, "extra": True}])
def test_confirmation_is_strict(value):
    with pytest.raises(ValidationError):
        RemakeCommand(client_operation_id=OP, **remake_request().model_dump(mode="python"), quote_confirmation=value)


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
@pytest.mark.parametrize("payment,products", [("CASH", 3250), ("CARD", 3250), ("CASH", 0), ("CARD", 0)])
def test_confirmed_uses_atomic_executor_and_exact_public_readback(actor, payment, products):
    db = Database(); command = run(confirmed(db, actor, payment, products)); service = OrderRemakeService(db)
    original = deepcopy(db.orders.documents[0])
    outcome = run(service.submit("parent", command, actor, financial_context=context(actor), signing_key=KEY))
    assert outcome.status_code == 201 and outcome.result.state == "applied"
    assert len(db.orders.documents) == 2 and len(db.audit_logs.documents) == 2 and db.counters.documents[0]["seq"] == 101
    row = db.order_operations.documents[0]
    assert "quote_confirmation" not in row["child_command"]
    assert row["child_command"]["client_operation_id"] == OP
    snapshot = row["financial_snapshot"]
    assert snapshot["products_bani"] == products and snapshot["restaurant_transport_bani"] == 1600
    assert snapshot["courier_remuneration_bani"] == 975
    assert snapshot["client_collection_bani"] == (products if payment == "CASH" else 0)
    assert db.orders.documents[0]["payment_type"] == original["payment_type"]
    db.order_operation_settings.documents.clear(); db.restaurant_tariff_versions.documents.clear(); db.restaurants.documents.clear()
    for action in [service.lookup("parent", OP, actor, financial_context=context(actor)),
                   service.resume("parent", OP, actor, financial_context=context(actor)),
                   service.submit("parent", command, actor, financial_context=context(actor), signing_key=lambda: pytest.fail("No key in recovery"))]:
        assert run(action).result.state == "replayed"
    result = run(service.readback("parent", OP, actor, financial_context=context(actor)))
    assert set(result) == {"contract_version", "kind", "actor_id", "actor_role", "restaurant_id", "client_operation_id",
        "quote_confirmation", "receipt", "parent", "child", "financial"}
    assert len(result["receipt"]) == 8 and result["receipt"]["state"] == "replayed"
    assert result["financial"]["advance_paid_bani"] is result["financial"]["refund_due_bani"] is result["financial"]["refund_paid_bani"] is None
    for forbidden in ["courier_remuneration_bani", "tariff_rule", "snapshot_digest", "operation_ref", *PII]:
        assert forbidden not in json.dumps(result)
    assert any(name == "orders" and session is not None for name, _, _, _, session in db.bounds)
    assert all(maximum <= 5 for name, _, maximum, _, _ in db.bounds if name in ("orders", "users", "order_operations"))


def test_single_sample_even_if_configuration_changes_after_hmac(monkeypatch):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    original = OrderFinancePreviewService.prepare_remake_confirmation
    async def change(self, *args):
        prepared = await original(self, *args)
        db.restaurant_tariff_versions.documents[0]["zones"]["z1"]["restaurant_transport_bani"] = 9999
        db.delivery_zones.documents.clear()
        return prepared
    monkeypatch.setattr(OrderFinancePreviewService, "prepare_remake_confirmation", change)
    assert run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY)).result.state == "pending"
    assert db.order_operations.documents[0]["financial_snapshot"]["restaurant_transport_bani"] == 1600


@pytest.mark.parametrize("change", ["draft", "tariff", "zone", "key"])
def test_valid_quote_mismatch_is_the_only_automatic_fence(change):
    db = Database(); command = run(confirmed(db)); service = pending_service(db); key = KEY
    if change == "draft": command.description = "Changed deliberate replacement"
    if change == "tariff": db.restaurant_tariff_versions.documents[0]["zones"]["z1"]["restaurant_transport_bani"] += 1
    if change == "zone": db.delivery_zones.documents[0]["name"] = "Changed zone"
    if change == "key": key = b"synthetic-other-key"
    result = run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=key))
    assert result.result.error_code == "FINANCIAL_QUOTE_CHANGED" and result.status_code == 409
    assert set(db.order_operations.documents[0]) == {"_id", "remake_terminal_contract_version", "terminal_kind", "actor_id",
        "actor_role", "restaurant_id", "target_order_id", "expected_order_version", "client_operation_id", "quote_confirmation",
        "state", "error_code", "error_status", "created_at", "resolved_at"}
    assert len(db.orders.documents) == 1 and db.audit_logs.documents == [] and service.executions == []


@pytest.mark.parametrize("change,code", [("marker", "FINANCIAL_REMAKE_NOT_ENABLED"), ("bad_marker", "CAPABILITIES_INVALID"),
    ("parent_version", "ORDER_VERSION_CONFLICT"), ("parent_status", "REMAKE_REQUIRES_DELIVERED"),
    ("missing_key", "FINANCIAL_PREVIEW_KEY_UNAVAILABLE"), ("grid", "FINANCIAL_GRID_UNAVAILABLE")])
def test_unavailable_candidate_never_creates_a_terminal(change, code):
    db = Database(); command = run(confirmed(db)); key = KEY
    if change == "marker": db.order_operation_settings.documents[0]["enabled"] = False
    if change == "bad_marker": db.order_operation_settings.documents[0]["enabled"] = "true"
    if change == "parent_version": db.orders.documents[0]["order_version"] += 1
    if change == "parent_status": db.orders.documents[0]["status"] = "NEW"
    if change == "missing_key": key = None
    if change == "grid": db.restaurant_tariff_versions.documents.clear()
    failure(OrderRemakeService(db).submit("parent", command, ADMIN, financial_context=context(), signing_key=key), code)
    assert db.order_operations.documents == [] and len(db.orders.documents) == 1


@pytest.mark.parametrize("field,value,code", [("status", "NEW", "REMAKE_REQUIRES_DELIVERED"),
    ("order_version", 9223372036854775807, "ORDER_VERSION_EXHAUSTED"), ("status", "DELIVERED", None)])
def test_parent_safe_context_and_eligibility(field, value, code):
    db = Database(); db.orders.documents[0][field] = value
    result = run(OrderRemakeService(db).parent_context("parent", RESTAURANT, financial_context=context(RESTAURANT)))
    assert result["eligibility"] == {"can_preview": code is None, "blocking_code": code}
    assert result["parent"]["customer_name"] == PII[0]
    assert not {"financial", "driver_id", "audit_trail", "financial_activity"} & result["parent"].keys()
    assert not any(method in ("insert_one", "update_one") for _, method, _ in db.events)


@pytest.mark.parametrize("collection", ["users", "orders", "restaurants", "order_operation_settings"])
def test_bounded_context_duplicates_fail_closed(collection):
    db = Database(); db.collections[collection].documents.append(deepcopy(db.collections[collection].documents[0]))
    with pytest.raises(CreationError):
        run(OrderRemakeService(db).parent_context("parent", ADMIN, financial_context=context()))
    assert db.order_operations.documents == []


@pytest.mark.parametrize("corruption", ["parent_link", "child_link", "private_amount", "parent_original", "child_version", "parent_version"])
def test_readback_validates_links_private_material_and_versions(corruption):
    db = Database(); command = run(confirmed(db)); service = OrderRemakeService(db)
    run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY))
    parent_doc, child = db.orders.documents
    if corruption == "parent_link": parent_doc["problem_followup_operation_ref"] = "wrong"
    if corruption == "child_link": child["linked_problem_order_id"] = "wrong"
    if corruption == "private_amount": child["financial"]["courier_remuneration_bani"] += 1
    if corruption == "parent_original": parent_doc["financial_contract_version"] = 1
    if corruption == "child_version": child["order_version"] = True
    if corruption == "parent_version": parent_doc["order_version"] = 4
    failure(service.readback("parent", OP, ADMIN, financial_context=context()), "REMAKE_READBACK_INVALID")


def test_readback_accepts_later_versions_and_status():
    db = Database(); command = run(confirmed(db)); service = OrderRemakeService(db)
    run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY))
    db.orders.documents[0]["order_version"] = 8
    db.orders.documents[1].update(order_version=3, status="DELIVERED")
    result = run(service.readback("parent", OP, ADMIN, financial_context=context()))
    assert result["receipt"]["parent_order_version"] == 5 and result["receipt"]["order_version"] == 0
    assert result["parent"]["order_version"] == 8 and result["child"]["order_version"] == 3


def test_original_financial_snapshot_is_immutable_without_inventing_settlement():
    from models.order_mutation import CreateOrderCommand
    from test_order_finance_preview import create_request
    db = Database(); service = OrderRemakeService(db)
    request = create_request("CARD", 9000)
    original_command = CreateOrderCommand(client_operation_id="original_finance_0001", **request.model_dump(mode="python"))
    snapshot, _ = run(OrderFinancePreviewService(db, signing_key=KEY).prepare_create_confirmation(original_command, ADMIN, "original-reference"))
    parent_doc = db.orders.documents[0]
    parent_doc.update(financial_contract_version=1, financial=snapshot, creation_operation_ref="original-reference",
        subtotal_amount=90, delivery_fee=16, total_amount=0, delivery_zone_id=snapshot["zone_id"],
        delivery_zone_name=snapshot["zone_name"], delivery_sector=snapshot["zone_sector"],
        delivery_zone_level=snapshot["zone_level"], zone=snapshot["zone_name"])
    before = deepcopy(snapshot)
    command = run(confirmed(db, payment="CASH", products=1305))
    assert run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY)).result.state == "applied"
    assert db.orders.documents[0]["financial"] == before
    result = run(service.readback("parent", OP, ADMIN, financial_context=context()))
    assert result["financial"]["products_bani"] == 1305 and result["financial"]["client_collection_bani"] == 1305
    assert result["financial"]["refund_due_bani"] is None
    assert not any(name == "order_financial_events" for name, _, _ in db.events)
