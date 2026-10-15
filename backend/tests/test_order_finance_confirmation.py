"""F2A synthetic owner probes. No app, environment loader or Mongo import."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from bson import BSON
import pytest
from pydantic import ValidationError
from pymongo.errors import AutoReconnect

from models.order_finance_preview import CreateFinancePreview
from models.order_mutation import CloseFinancialCreation, CreateOrderCommand, QuoteConfirmation, build_mutation_intent
from utils.order_creation import CreationError, OrderCreationService, VerifiedFinancialContext, _validated_operation, operation_key
from utils.order_finance import admission_snapshot
from utils.order_finance_preview import OrderFinancePreviewService
from test_order_finance_preview import ADMIN, KEY, PII, Database as PreviewDatabase, Cursor, create_request
from test_order_creation_ui_bridge import Collection as BridgeCollection, Session

OP = "financial_confirm_owner_0001"
CONTEXT = VerifiedFinancialContext(ADMIN["id"], "admin", None)


class Collection(BridgeCollection):
    async def insert_one(self, document, session=None):
        if self.db.before_insert:
            await self.db.before_insert(self.name, deepcopy(document))
        if self.db.fail_before_insert:
            raise AutoReconnect("Synthetic unavailable before write")
        await super().insert_one(document, session)
        if self.db.fail_after_insert:
            raise AutoReconnect("Synthetic lost acknowledgement")

    def aggregate(self, pipeline, maxTimeMS):
        assert maxTimeMS == 2000 and len(pipeline) == 3
        self.event("aggregate")
        query, maximum = pipeline[0]["$match"], pipeline[1]["$limit"]
        size = pipeline[2]["$project"]["document"]["$cond"][0]["$lte"][1]
        assert 1 <= maximum <= 301 and size <= 131072
        docs = [doc for doc in self.documents if all(doc.get(k) == v for k, v in query.items())][:maximum]
        return Cursor([{"document": deepcopy(doc) if len(BSON.encode(doc)) <= size else None} for doc in docs])


class Database:
    def __init__(self):
        self.events, self.reads, self.collection_options = [], [], []
        self.before_insert = None
        self.fail_before_insert = self.fail_after_insert = False
        rows = deepcopy(PreviewDatabase().rows)
        rows.update(order_operations=[], orders=[], audit_logs=[], counters=[{"_id": "orders.global", "seq": 100}])
        for name in ("users", "restaurants"):
            for i, doc in enumerate(rows[name]):
                doc["_id"] = f"synthetic-{name}-{i}"
        self.collections = {name: Collection(self, name, docs) for name, docs in rows.items()}
        self.client = SimpleNamespace(start_session=self.start_session)

    def __getattr__(self, name):
        return self.collections[name]

    def get_collection(self, name, **options):
        self.collection_options.append((name, options))
        return self.collections[name]

    async def command(self, name, **options):
        assert name == "hello"
        self.events.append(("database", "hello", False))
        return {"setName": "synthetic-owner-only"}

    async def start_session(self):
        return Session(self)


def run(awaitable):
    return asyncio.run(awaitable)


async def confirmed(db, *, payment="CASH", products=3250, operation_id=OP):
    request = create_request(payment, products)
    preview = await OrderFinancePreviewService(db, signing_key=KEY).quote_create(request, ADMIN)
    return CreateOrderCommand(client_operation_id=operation_id, **request.model_dump(mode="python"),
        quote_confirmation={"contract_version": 1, "quote_fingerprint": preview["quote_fingerprint"]})


def close_body(command):
    return CloseFinancialCreation(restaurant_id=command.order.restaurant_id, quote_confirmation=command.quote_confirmation)


def pending_service(db):
    service = OrderCreationService(db)
    service.executions = []
    async def execute(key, actor, operation_id, **kwargs):
        service.executions.append(key)
        _validated_operation(await service.operations.find_one({"_id": key}), key, actor, kwargs.get("financial_context"))
        return service._pending(operation_id)
    service._execute = execute
    return service


def failure(awaitable, code):
    with pytest.raises(CreationError) as caught:
        run(awaitable)
    assert caught.value.code == code
    assert all(value not in str(caught.value) for value in PII)


@pytest.mark.parametrize("financial", [False, True])
def test_absent_confirmation_does_not_change_historical_payload_or_digest(financial):
    request = create_request().model_dump(mode="python")
    if not financial:
        request.pop("financial")
    command = CreateOrderCommand(client_operation_id=OP, **request)
    dumped = command.model_dump(mode="json")
    assert "quote_confirmation" not in dumped
    assert ("financial" in dumped) == financial
    from hashlib import sha256
    canonical = json.dumps({"contract_version": 1, "type": "create", "target": None,
        "payload": {key: value for key, value in dumped.items() if key != "client_operation_id"}},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert build_mutation_intent(ADMIN["id"], "create", None, command).payload_digest == sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize("value", [None, {}, {"contract_version": True, "quote_fingerprint": "a"*64},
    {"contract_version": 1.0, "quote_fingerprint": "a"*64}, {"contract_version": 2, "quote_fingerprint": "a"*64},
    {"contract_version": 1, "quote_fingerprint": "A"*64}, {"contract_version": 1, "quote_fingerprint": "a"*63},
    {"contract_version": 1, "quote_fingerprint": "a"*64, "extra": True}])
def test_confirmation_strict(value):
    with pytest.raises(ValidationError):
        CreateOrderCommand(client_operation_id=OP, **create_request().model_dump(mode="python"), quote_confirmation=value)


def test_confirmation_requires_financial_and_changes_digest():
    db = Database(); command = run(confirmed(db))
    data = command.model_dump(mode="python")
    old = CreateOrderCommand.model_validate({key: value for key, value in data.items() if key != "quote_confirmation"})
    assert build_mutation_intent(ADMIN["id"], "create", None, command).payload_digest != build_mutation_intent(ADMIN["id"], "create", None, old).payload_digest
    data.pop("financial")
    with pytest.raises(ValidationError): CreateOrderCommand.model_validate(data)


@pytest.mark.parametrize("payment,products", [("CASH", 3250), ("CARD", 3250), ("CASH", 0), ("CARD", 0)])
def test_exact_confirmed_amounts_use_existing_executor(payment, products):
    db = Database(); command = run(confirmed(db, payment=payment, products=products))
    service = OrderCreationService(db)
    result = run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY))
    assert result.result.state == "applied" and result.status_code == 201
    operation = db.order_operations.documents[0]
    snapshot = admission_snapshot(operation, command)
    assert snapshot.operation_ref == operation["_id"] and snapshot.products_bani == products
    assert snapshot.restaurant_transport_bani == 1600 and snapshot.courier_remuneration_bani == 975
    assert snapshot.client_collection_bani == (products if payment == "CASH" else 0)
    assert snapshot.advance_paid_bani is snapshot.refund_due_bani is snapshot.refund_paid_bani is None
    assert len(db.orders.documents) == len(db.audit_logs.documents) == 1
    assert db.counters.documents[0]["seq"] == 101
    db.order_operation_settings.documents.clear(); db.restaurant_tariff_versions.documents.clear()
    for entry in (service.lookup(OP, ADMIN, financial_context=CONTEXT),
                  service.resume(OP, ADMIN, financial_context=CONTEXT),
                  service.create(command, ADMIN, financial_context=CONTEXT, signing_key=lambda: pytest.fail("replay must not read key"))):
        assert run(entry).result.state == "replayed"
    assert len(db.orders.documents) == len(db.audit_logs.documents) == 1


def test_material_not_refetched_between_hmac_and_admission(monkeypatch):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    original = OrderFinancePreviewService.prepare_create_confirmation
    async def change_after_sample(self, *args):
        result = await original(self, *args)
        db.restaurant_tariff_versions.documents[0]["zones"]["z1"]["restaurant_transport_bani"] = 9999
        db.delivery_zones.documents.clear()
        return result
    monkeypatch.setattr(OrderFinancePreviewService, "prepare_create_confirmation", change_after_sample)
    assert run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY)).result.state == "pending"
    assert db.order_operations.documents[0]["financial_snapshot"]["restaurant_transport_bani"] == 1600


@pytest.mark.parametrize("change", ["draft", "tariff", "zone", "key"])
def test_changed_confirmation_is_durable_rejection_without_financial_effect(change):
    db = Database(); command = run(confirmed(db)); service = pending_service(db); key = KEY
    if change == "draft":
        data = command.model_dump(mode="python"); data["order"]["notes"] = "Changed synthetic note"
        command = CreateOrderCommand.model_validate(data)
    if change == "tariff": db.restaurant_tariff_versions.documents[0]["zones"]["z1"]["courier_remuneration_bani"] = 1234
    if change == "zone": db.delivery_zones.documents[0]["name"] = "Changed synthetic zone"
    if change == "key": key = b"rotated-synthetic-owner-key"
    result = run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=key))
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_QUOTE_CHANGED"
    row = db.order_operations.documents[0]
    assert not {"command", "financial_snapshot", "payload_digest", "order_id"} & row.keys()
    assert service.executions == [] and db.counters.documents[0]["seq"] == 100
    assert db.orders.documents == db.audit_logs.documents == []
    assert run(service.lookup(OP, ADMIN, financial_context=CONTEXT)).result == result.result


@pytest.mark.parametrize("change", ["missing_grid", "bad_grid", "duplicate_grid", "bad_zone", "marker_off", "bad_marker", "key", "amount", "disabled"])
def test_unavailable_or_invalid_configuration_never_fences(change):
    db = Database(); command = run(confirmed(db)); key = KEY
    if change == "missing_grid": db.restaurant_tariff_versions.documents.clear()
    if change == "bad_grid": db.restaurant_tariff_versions.documents[0]["unexpected"] = True
    if change == "duplicate_grid": db.restaurant_tariff_versions.documents *= 2
    if change == "bad_zone": db.delivery_zones.documents[0]["polygon"] = []
    if change == "marker_off": db.order_operation_settings.documents[0]["enabled"] = False
    if change == "bad_marker": db.order_operation_settings.documents[0]["enabled"] = "false"
    if change == "key": key = " "
    if change == "amount":
        data = command.model_dump(mode="python"); data["order"]["total_amount"] = 31.0
        command = CreateOrderCommand.model_validate(data)
    if change == "disabled": db.users.documents[0]["account_disabled"] = True
    with pytest.raises(CreationError):
        run(pending_service(db).create(command, ADMIN, financial_context=CONTEXT, signing_key=key))
    assert db.order_operations.documents == []
    assert db.counters.documents[0]["seq"] == 100


def test_context_required_before_any_confirmed_create_write():
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    for context in (None, {}, VerifiedFinancialContext("foreign", "admin", None), VerifiedFinancialContext(ADMIN["id"], "admin", "foreign")):
        failure(service.create(command, ADMIN, financial_context=context, signing_key=KEY), "FINANCIAL_CONTEXT_REQUIRED")
    assert db.order_operations.documents == []


def test_pending_resume_uses_stored_snapshot_after_key_grid_zone_and_marker_changes():
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY))
    frozen = deepcopy(db.order_operations.documents[0]["financial_snapshot"])
    db.order_operation_settings.documents.clear(); db.restaurant_tariff_versions.documents.clear()
    db.delivery_zones.documents.clear()
    result = run(OrderCreationService(db).resume(OP, ADMIN, financial_context=CONTEXT))
    assert result.result.state == "applied"
    assert db.order_operations.documents[0]["financial_snapshot"] == frozen
    assert db.orders.documents[0]["financial"] == frozen
    assert db.counters.documents[0]["seq"] == 101 and len(db.audit_logs.documents) == 1
