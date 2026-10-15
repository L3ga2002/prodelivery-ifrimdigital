"""Financial quotation at admission, immutable recovery, and exact bani values.

No configuration writes, provider calls, migrations, or activation occur here.
The legacy aggregate is retained as a display projection, never repriced.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
import json

from bson.int64 import Int64
from pydantic import ValidationError

from models.order_finance import (
    FinancialCreateRequest, FinancialSnapshot, MAX_EARNED_BANI, MAX_MONEY_BANI,
    RestaurantTariffVersion,
)


SETTINGS_ID = "order-finance-v1"


class FinanceError(ValueError):
    def __init__(self, code, message="Datele financiare necesita verificare; nu a fost aplicat un tarif implicit.", status_code=409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def exact_bani(value):
    """Compatibility boundary only. Reject excess precision instead of rounding."""
    if type(value) not in (int, Int64, float, Decimal):
        raise FinanceError("FINANCIAL_AMOUNT_INVALID")
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value() or not 0 <= amount <= MAX_MONEY_BANI:
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError, OverflowError):
        raise FinanceError("FINANCIAL_AMOUNT_INVALID") from None


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def validate_snapshot(value):
    try:
        snapshot = FinancialSnapshot.model_validate(value)
        when = datetime.fromisoformat(snapshot.snapshot_at)
        if when.tzinfo is None or when.utcoffset() != timezone.utc.utcoffset(when):
            raise ValueError()
        data = snapshot.model_dump(mode="json")
        digest = data.pop("snapshot_digest")
        if not hmac.compare_digest(digest, _digest(data)):
            raise ValueError()
        return snapshot
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise FinanceError("FINANCIAL_SNAPSHOT_INVALID") from None


def order_financial_snapshot(order):
    """Presence of either marker selects fail-closed financial validation."""
    if "financial" not in order and "financial_contract_version" not in order:
        return None
    if type(order.get("financial_contract_version")) not in (int, Int64) or order["financial_contract_version"] != 1:
        raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
    snapshot = validate_snapshot(order.get("financial"))
    if (snapshot.restaurant_id != order.get("restaurant_id")
            or snapshot.operation_ref != order.get("creation_operation_ref")
            or (snapshot.collection_mode == "cash") != (order.get("payment_type") == "CASH")
            or order.get("payment_type") not in ("CASH", "CARD")
            or exact_bani(order.get("subtotal_amount")) != snapshot.products_bani
            or exact_bani(order.get("delivery_fee")) != snapshot.restaurant_transport_bani
            or exact_bani(order.get("total_amount")) != snapshot.client_collection_bani):
        raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
    if any(order.get(field) != value for field, value in {
        "delivery_zone_id": snapshot.zone_id, "delivery_zone_name": snapshot.zone_name,
        "delivery_sector": snapshot.zone_sector, "delivery_zone_level": snapshot.zone_level, "zone": snapshot.zone_name,
    }.items()):
        raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
    return snapshot


def admission_snapshot(operation, command):
    requested = command.financial
    if requested is None:
        if "financial_snapshot" in operation:
            raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
        return None
    snapshot = validate_snapshot(operation.get("financial_snapshot"))
    if (snapshot.operation_ref != operation.get("_id") or snapshot.restaurant_id != command.order.restaurant_id
            or snapshot.tariff_version != requested.tariff_version or snapshot.products_bani != requested.products_bani
            or snapshot.basis != requested.basis or snapshot.zone_id != requested.zone_id
            or snapshot.route_distance_m != requested.route_distance_m
            or snapshot.distance_evidence_ref != requested.distance_evidence_ref
            or (snapshot.collection_mode == "cash") != (command.order.payment_type == "CASH")):
        raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
    validate_request_amounts(command.order, requested)
    return snapshot


def validate_request_amounts(order, request):
    # Opt-in callers identify products exactly; transport comes only from the
    # selected server tariff. No old products+transport total is repurposed.
    if exact_bani(order.total_amount) != request.products_bani:
        raise FinanceError("FINANCIAL_PRODUCTS_MISMATCH")
    if order.subtotal_amount is not None and exact_bani(order.subtotal_amount) != request.products_bani:
        raise FinanceError("FINANCIAL_PRODUCTS_MISMATCH")
    if order.delivery_fee is not None:
        raise FinanceError("FINANCIAL_CLIENT_TARIFF_FORBIDDEN")
    if order.linked_problem_order_id is not None or order.problem_type is not None:
        raise FinanceError("FINANCIAL_REMAKE_PROTOCOL_REQUIRED")
    for item in order.items:
        exact_bani(item.price)


async def guard_generic_problem_link(database, order, session=None):
    """Legacy links stay legacy; generic creation cannot bypass a versioned parent.

    The caller must first authorize creation for order.restaurant_id. A foreign
    parent is indistinguishable from a missing one and never loaded by ID alone.
    """
    if order.linked_problem_order_id is None:
        return
    parent = await database.orders.find_one({"id": order.linked_problem_order_id,
        "restaurant_id": order.restaurant_id}, {"id": 1, "order_version": 1,
        "financial": 1, "financial_contract_version": 1}, session=session)
    if parent is None:
        raise FinanceError("PROBLEM_PARENT_NOT_AVAILABLE", "Comanda initiala nu este disponibila.", 404)
    if any(name in parent for name in ("order_version", "financial", "financial_contract_version")):
        raise FinanceError("FINANCIAL_REMAKE_PROTOCOL_REQUIRED")


async def quote_at_admission(database, command, actor, operation_ref, detected_zone):
    request = command.financial
    if request is None:
        return None
    setting = await database.order_operation_settings.find_one({"_id": SETTINGS_ID})
    if not setting or setting.get("enabled") is not True:
        raise FinanceError("FINANCIAL_NOT_ENABLED", "Protocolul financiar nou nu este activat.", 503)
    validate_request_amounts(command.order, request)
    if command.order.customer_latitude is None or command.order.customer_longitude is None:
        raise FinanceError("FINANCIAL_ZONE_UNVERIFIED")
    if request.basis == "zone":
        if detected_zone is None or detected_zone.get("id") != request.zone_id:
            raise FinanceError("FINANCIAL_ZONE_MISMATCH")
    elif detected_zone is not None:
        raise FinanceError("FINANCIAL_ZONE_MISMATCH")
    elif actor.get("role") != "admin":
        # Until an approved routing adapter exists, only explicit administrator
        # road-distance evidence may support an outside-zone quotation.
        raise FinanceError("FINANCIAL_DISTANCE_AUTHORITY_REQUIRED", status_code=403)
    docs = await database.restaurant_tariff_versions.find({
        "restaurant_id": command.order.restaurant_id, "version": request.tariff_version,
    }, {"_id": 0}).limit(2).to_list(2)
    if not docs:
        raise FinanceError("FINANCIAL_GRID_MISSING")
    if len(docs) != 1:
        raise FinanceError("FINANCIAL_GRID_INVALID")
    try:
        grid = RestaurantTariffVersion.model_validate(docs[0])
    except ValidationError:
        raise FinanceError("FINANCIAL_GRID_INVALID") from None
    if not grid.approved:
        raise FinanceError("FINANCIAL_GRID_NOT_APPROVED")
    if request.basis == "zone":
        rule = grid.zones.get(request.zone_id)
        if rule is None or rule.restaurant_transport_bani is None or rule.courier_remuneration_bani is None:
            raise FinanceError("FINANCIAL_GRID_INCOMPLETE")
        transport, remuneration = rule.restaurant_transport_bani, rule.courier_remuneration_bani
        selected = {"restaurant_transport_bani": transport, "courier_remuneration_bani": remuneration,
                    "distance_rounding": None, "restaurant_rate_per_km_bani": None, "restaurant_minimum_bani": None}
    else:
        rule = grid.outside
        if rule is None or rule.courier_remuneration_bani is None:
            raise FinanceError("FINANCIAL_GRID_INCOMPLETE")
        transport = max(rule.restaurant_minimum_bani, request.route_distance_m // 1000 * rule.restaurant_rate_per_km_bani)
        remuneration = rule.courier_remuneration_bani
        selected = {"restaurant_transport_bani": transport, "courier_remuneration_bani": remuneration,
                    "distance_rounding": rule.distance_rounding, "restaurant_rate_per_km_bani": rule.restaurant_rate_per_km_bani,
                    "restaurant_minimum_bani": rule.restaurant_minimum_bani}
    cash = command.order.payment_type == "CASH"
    data = {"contract_version": 1, "currency": "RON", "restaurant_id": grid.restaurant_id,
            "tariff_version": grid.version, "operation_ref": operation_ref, "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "products_bani": request.products_bani, "collection_mode": "cash" if cash else "prepaid",
            "client_collection_bani": request.products_bani if cash else 0,
            "restaurant_transport_bani": transport, "courier_remuneration_bani": remuneration,
            "advance_required_bani": request.products_bani if cash else 0,
            "advance_paid_bani": None, "refund_due_bani": None, "refund_paid_bani": None,
            "basis": request.basis, "zone_id": request.zone_id, "route_distance_m": request.route_distance_m,
            "zone_name": detected_zone.get("name") if detected_zone else None,
            "zone_sector": detected_zone.get("sector") if detected_zone else None,
            "zone_level": detected_zone.get("zone_level") if detected_zone else None,
            "distance_evidence_ref": request.distance_evidence_ref, "tariff_rule": selected}
    data["snapshot_digest"] = _digest(data)
    return validate_snapshot(data).model_dump(mode="json")


def financial_earned_total(driver, increment):
    current = driver.get("financial_earned_bani", 0)
    if (type(current) not in (int, Int64) or not 0 <= current <= MAX_EARNED_BANI
            or current + increment > MAX_EARNED_BANI):
        raise FinanceError("FINANCIAL_DRIVER_TOTAL_INVALID")
    return int(current) + increment
