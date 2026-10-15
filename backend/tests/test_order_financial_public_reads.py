"""Synthetic P1 contract oracles. No application/environment/DB imports."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.order import Order
from models.order_financial_reads import PublicOrderFinancial, AssignedDriverOrderFinancial, ReadContext
from utils.order_reads import OrderReadService, safe_order, safe_history, _order_projection, _identity_projection
from utils.order_financial_reads import project_order, project_history, project_outer, OUTER_FIELDS
from utils.order_financial_reads import READ_DEADLINE


SECRET = "PRIVATE-P1-PROVENANCE"
ADMIN = {"id": "admin", "role": "admin"}
RESTAURANT = {"id": "restaurant-user", "role": "restaurant", "restaurant_id": "r1"}
DRIVER = {"id": "driver-user", "role": "driver", "driver_id": "d1"}


def snapshot(payment="CASH", basis="zone"):
    value = {"contract_version": 1, "currency": "RON", "restaurant_id": "r1", "tariff_version": "public-tariff",
        "operation_ref": SECRET, "snapshot_at": "2026-10-15T00:00:00+00:00", "products_bani": 4321,
        "collection_mode": "cash" if payment == "CASH" else "prepaid", "client_collection_bani": 4321 if payment == "CASH" else 0,
        "restaurant_transport_bani": 1600, "courier_remuneration_bani": 917, "advance_required_bani": 4321 if payment == "CASH" else 0,
        "advance_paid_bani": None, "refund_due_bani": None, "refund_paid_bani": None, "basis": basis,
        "zone_id": "z1" if basis == "zone" else None, "zone_name": "Zone One" if basis == "zone" else None,
        "zone_sector": None, "zone_level": None, "route_distance_m": None if basis == "zone" else 1000,
        "distance_evidence_ref": None if basis == "zone" else SECRET,
        "tariff_rule": {"restaurant_transport_bani": 1600, "courier_remuneration_bani": 917,
            "distance_rounding": None if basis == "zone" else "floor_km", "restaurant_rate_per_km_bani": None if basis == "zone" else 1600,
            "restaurant_minimum_bani": None if basis == "zone" else 0}}
    value["snapshot_digest"] = sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    return value


def financial_order(payment="CASH", basis="zone"):
    f = snapshot(payment, basis)
    return {"id": "o1", "order_number": "S.1", "source": "S", "restaurant_id": "r1", "restaurant_name": "Synthetic",
        "driver_id": "d1", "driver_name": "Synthetic Driver", "status": "NEW", "order_version": 0,
        "customer_name": "Synthetic", "customer_phone": "0700000000", "customer_address": "Synthetic address",
        "customer_latitude": 0.0, "customer_longitude": 0.0, "notes": "Manual notes", "items": [], "payment_type": payment,
        "subtotal_amount": f["products_bani"] / 100, "total_amount": f["client_collection_bani"] / 100,
        "delivery_fee": f["restaurant_transport_bani"] / 100, "financial_contract_version": 1, "financial": f,
        "creation_operation_ref": f["operation_ref"], "delivery_zone_id": f["zone_id"], "delivery_zone_name": f["zone_name"],
        "delivery_sector": f["zone_sector"], "delivery_zone_level": f["zone_level"], "zone": f["zone_name"],
        "created_at": "2026-10-15T00:00:00+00:00", "audit_trail": [], "private_unknown": {"operation_ref": SECRET}}


def legacy_order():
    return Order(order_number="S.2", restaurant_id="r1", restaurant_name="Synthetic", driver_id="d1",
        customer_name="Synthetic", customer_phone="0700000000", customer_address="Synthetic address", total_amount=10,
        payment_type="CASH", id="o1", created_at="2026-10-15T00:00:00Z").model_dump(mode="json")


def context(actor):
    return ReadContext(actor["id"], actor["role"], actor.get("restaurant_id"), actor.get("driver_id"))


def projected(document):
    doc = deepcopy(document)
    doc.update(_read_has_revision="order_version" in doc, _read_has_preparation_status="preparation_status" in doc,
        _read_has_financial="financial" in doc or "financial_contract_version" in doc,
        _read_has_financial_activity="financial_activity" in doc or "financial_activity_contract_version" in doc,
        _read_has_custody="custody_activity" in doc or "custody_contract_version" in doc,
        _read_multi_fields=[], _read_id=doc.get("id", ""), _read_date=doc.get("created_at"), _read_compat_raw=deepcopy(document))
    doc.update(_history=[{**entry, "index": i} for i, entry in enumerate(doc.get("audit_trail", []))],
        _history_start=0, _history_end=len(doc.get("audit_trail", [])), _history_invalid=False)
    # Mongo's conditional projection emits null for absent financial containers;
    # the explicit presence bits, not these synthetic nulls, define legacy.
    for field in ("financial", "financial_contract_version", "financial_activity", "financial_activity_contract_version",
                  "custody_activity", "custody_contract_version", "creation_operation_ref"):
        doc.setdefault(field, None)
    if any(k.startswith("read_") for k in document):
        doc["_read_invalid"] = True
    return doc


def matches(document, query):
    for key, value in query.items():
        if key == "$and":
            if not all(matches(document, q) for q in value): return False
        elif key.startswith("$"): continue
        elif isinstance(value, dict):
            if "$in" in value and document.get(key) not in value["$in"]: return False
            if "$nin" in value and document.get(key) in value["$nin"]: return False
        elif document.get(key) != value: return False
    return True


class Cursor:
    def __init__(self, values, owner): self.values, self.owner = values, owner
    async def to_list(self, length):
        if self.owner.fault: raise self.owner.fault
        if self.owner.on_read: self.owner.on_read()
        return deepcopy(self.values[:length])
    async def close(self): self.owner.closed += 1


class Collection:
    def __init__(self, values=(), kind="other"):
        self.values, self.kind, self.calls, self.closed = deepcopy(list(values)), kind, [], 0
        self.fault, self.on_read = None, None
    def aggregate(self, pipeline, **kwargs):
        assert kwargs["maxTimeMS"] == 3000
        self.calls.append((deepcopy(pipeline), kwargs))
        values = [d for d in self.values if matches(d, pipeline[0]["$match"])]
        projection = pipeline[-1].get("$project", {})
        if "value" in projection:
            fields = projection["value"]["$cond"][1]
            values = [{"value": {k: d[k] for k in fields if k in d}} for d in values]
        elif self.kind == "orders":
            values = [projected(d) for d in values]
        return Cursor(values, self)
    async def count_documents(self, query, **kwargs):
        assert kwargs.get("maxTimeMS") == 3000
        return sum(matches(d, query) for d in self.values)
    def __getattr__(self, name):
        if name in {"insert_one", "update_one", "update_many", "delete_one", "delete_many", "replace_one"}:
            raise AssertionError("GET attempted write")
        raise AttributeError(name)


def database(orders=None):
    return SimpleNamespace(users=Collection([ADMIN, RESTAURANT, DRIVER]),
        drivers=Collection([{"id": "d1", "user_id": "driver-user", "name": "Synthetic Driver", "total_deliveries": 0,
            "total_earnings": 0, "financial_earned_bani": 123, "punctuality_rate": .85, "joined_at": "2026-10-01T00:00:00Z"}]),
        restaurants=Collection([{"id": "r1", "name": "Synthetic", "program": "10-22", "private_unknown": SECRET}]),
        orders=Collection([financial_order()] if orders is None else orders, "orders"), schedules=Collection(),
        driver_avatars=Collection(), audit_logs=Collection(), order_custody_events=Collection(), order_incidents=Collection(), order_financial_events=Collection())


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT, DRIVER], ids=["admin", "restaurant", "driver"])
@pytest.mark.parametrize("payment,basis", [("CASH", "zone"), ("CARD", "zone"), ("CASH", "outside"), ("CARD", "outside")])
def test_exact_role_projection_and_no_mutation(actor, payment, basis):
    original = financial_order(payment, basis); before = deepcopy(original)
    full = safe_order(original, set()); value = project_order(full, context(actor))
    assert original == before
    assert value["financial"]["client_collection_bani"] == before["financial"]["client_collection_bani"]
    assert value["customer_latitude"] == value["customer_longitude"] == 0
    if actor is ADMIN:
        assert value["financial"] == before["financial"]
        assert "financial_read_visibility" not in value
    else:
        assert SECRET not in json.dumps(value)
        assert value["financial_read_contract_version"] == 1
        assert ("courier_remuneration_bani" in value["financial"]) == (actor is DRIVER)
        assert not any(k in value["financial"] for k in ("snapshot_digest", "tariff_rule", "operation_ref"))


@pytest.mark.parametrize("field", ["snapshot_digest", "courier_remuneration_bani", "tariff_rule", "operation_ref"])
def test_corrupt_private_material_cannot_be_hidden_as_valid(field):
    order = financial_order(); order["financial"][field] = SECRET + "-corrupt"
    value = project_order(safe_order(order, set()), context(RESTAURANT))
    assert value["financial"] is None and value["read_financial_invalid"] and value["read_actions_unavailable"]
    assert SECRET not in json.dumps(value)


@pytest.mark.parametrize("bad", [True, False, "1", 1.2, -1, None, 100000001])
def test_public_model_money_is_strict(bad):
    value = project_order(safe_order(financial_order(), set()), context(RESTAURANT))["financial"]
    value["products_bani"] = bad
    with pytest.raises(ValidationError): PublicOrderFinancial.model_validate(value)


@pytest.mark.parametrize("field", ["advance_paid_bani", "refund_due_bani", "refund_paid_bani"])
def test_paid_values_are_exact_null(field):
    value = project_order(safe_order(financial_order(), set()), context(RESTAURANT))["financial"]
    value[field] = 0
    with pytest.raises(ValidationError): PublicOrderFinancial.model_validate(value)


def test_public_model_rejects_private_keys_and_bool_contract():
    value = project_order(safe_order(financial_order(), set()), context(RESTAURANT))["financial"]
    for changes in ({"contract_version": True}, {"courier_remuneration_bani": 917}, {"snapshot_digest": "a" * 64}, {"unknown": None}):
        with pytest.raises(ValidationError): PublicOrderFinancial.model_validate({**value, **changes})
    assert AssignedDriverOrderFinancial.model_validate({**value, "courier_remuneration_bani": 917}).courier_remuneration_bani == 917


def test_legacy_real_serializer_and_only_compat_generated_false_omitted():
    raw = legacy_order()
    assert "financial" not in raw and "order_version" not in raw
    for actor in (ADMIN, RESTAURANT, DRIVER):
        result = asyncio.run(OrderReadService(database([raw])).compatibility(actor))[0]
        assert "financial" not in result and "order_version" not in result and "read_actions_unavailable" not in result
    for marker in (False, True, None, "invalid"):
        result = asyncio.run(OrderReadService(database([{**raw, "read_actions_unavailable": marker}])).compatibility(RESTAURANT))[0]
        assert result["read_actions_unavailable"] is True


@pytest.mark.parametrize("actor,change", [(RESTAURANT, {"role": "admin"}), (RESTAURANT, {"restaurant_id": "r2"}), (DRIVER, {"driver_id": "d2"})])
def test_current_authority_change_refuses(actor, change):
    db = database()
    for row in db.users.values:
        if row["id"] == actor["id"]: row.update(change)
    with pytest.raises(HTTPException): asyncio.run(OrderReadService(db).compatibility(actor))


@pytest.mark.parametrize("bad", [True, None, 0, 1, "false", {}])
def test_disabled_flags_strict(bad):
    db = database(); db.users.values[1]["account_disabled"] = bad
    with pytest.raises(HTTPException): asyncio.run(OrderReadService(db).authorize_read(RESTAURANT))


def test_revalidate_after_last_database_await_blocks_role_change():
    db = database(); db.orders.on_read = lambda: db.users.values[1].update(role="admin")
    with pytest.raises(HTTPException) as caught: asyncio.run(OrderReadService(db).compatibility(RESTAURANT))
    assert caught.value.status_code == 403


def test_duplicates_missing_foreign_and_history_redaction():
    for orders, status in (([], 404), ([financial_order(), financial_order()], 409)):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(OrderReadService(database(orders)).compatibility(RESTAURANT, kind="one", identifier_value="o1"))
        assert caught.value.status_code == status
    entry = {"index": 0, "id": "history", "action": "created", "performed_by": "admin", "performed_by_role": "admin",
        "created_at": "2026-10-15T00:00:00Z", "changes": {"financial_snapshot_digest": "a" * 64, "courier_remuneration_bani": 917, "notes": "Keep"}}
    full = safe_history(entry, set())
    assert "courier_remuneration_bani" in project_history([full], context(ADMIN))[0]["changes"]
    assert project_history([full], context(RESTAURANT))[0]["changes"] == {"notes": "Keep"}


def test_incident_public_whitelist_and_overflow_invalid():
    raw = legacy_order(); raw["incident_summary"] = [{"id": "incident", "incident_type": "other", "operation_ref": SECRET}]
    value = safe_order(raw, set()); assert value["incident_summary"] == [{"id": "incident", "incident_type": "other"}]
    raw["incident_summary"] *= 51
    value = safe_order(raw, set()); assert value["incident_summary"] is None and value["read_actions_unavailable"]


def test_projection_limits_and_context_required():
    projection = json.dumps(_order_projection(include_raw=True), default=str)
    assert '10000' in projection and '8192' in projection and '65536' in projection and '$slice' in projection
    identity = json.dumps(_identity_projection(("id", "role", "driver_id")))
    assert '$strLenBytes' in identity and '480' in identity and '_read_identity_invalid' in identity
    with pytest.raises(HTTPException): project_order(safe_order(financial_order(), set()), None)
    with pytest.raises(HTTPException): asyncio.run(OrderReadService(database()).authorize_read({"id": "driver-user", "role": "driver"}))


def test_outer_containers_drop_nested_provenance_preserve_own_pay():
    driver = project_outer({"id": "d1", "financial_earned_bani": 900, "private": SECRET, "operation_ref": SECRET}, "driver")
    assert driver == {"id": "d1", "financial_earned_bani": 900}
    schedule = project_outer({"id": "s1", "slots": {"monday": [{"start": "10:00", "end": "11:00", "operation_ref": SECRET}]}}, "schedule")
    assert SECRET not in json.dumps(schedule)


@pytest.mark.parametrize("field", ["financial", "financial_contract_version"])
def test_original_explicit_null_is_invalid_despite_projection_null_defaults(field):
    raw = legacy_order(); raw[field] = None
    value = asyncio.run(OrderReadService(database([raw])).compatibility(RESTAURANT))[0]
    assert value["financial"] is None and value["read_financial_invalid"] is True
    assert value["financial_read_visibility"] == "restaurant"


def test_compatibility_date_stage_precedes_projection_and_proof_cursors_close():
    db = database(); service = OrderReadService(db)
    asyncio.run(service.compatibility(RESTAURANT))
    pipeline = db.orders.calls[0][0]
    assert any("_read_date" in stage.get("$set", {}) for stage in pipeline[:-1])
    for name in ("order_financial_events", "order_custody_events", "order_incidents"):
        collection = getattr(db, name)
        result = getattr(service.proof_reads, name).aggregate([{"$match": {"_id": {"$in": ["exact"]}}}, {"$limit": 2}], maxTimeMS=3000)
        assert asyncio.run(result.to_list(2)) == []
        assert collection.closed == 1 and collection.calls[0][1]["allowDiskUse"] is False
        collection.fault = RuntimeError("private failure")
        with pytest.raises(RuntimeError): asyncio.run(result.to_list(2))
        assert collection.closed == 2


def test_authorization_and_late_reads_share_explicit_deadline():
    async def run():
        db = database()
        class WaitingCursor(Cursor):
            async def to_list(self, length):
                await asyncio.sleep(1)
        db.users.aggregate = lambda *a, **kw: WaitingCursor([], db.users)
        marker = READ_DEADLINE.set(asyncio.get_running_loop().time() + .01)
        try:
            with pytest.raises(HTTPException) as caught: await OrderReadService(db).authorize_read(RESTAURANT)
            assert caught.value.status_code == 503 and db.users.closed == 1
        finally: READ_DEADLINE.reset(marker)
    asyncio.run(run())
