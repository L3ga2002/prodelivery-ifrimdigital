"""Financial v1 oracles; synthetic inputs, no app/environment imports."""

import asyncio
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from models.order import Order
from models.order_finance import FinancialCreateRequest
from models.order_mutation import CreateOrderCommand, build_mutation_intent
from utils.order_finance import (
    FinanceError, admission_snapshot, exact_bani, financial_earned_total,
    order_financial_snapshot, quote_at_admission, validate_snapshot,
)
from utils.order_reads import safe_order
from utils.order_revision import ensure_legacy_order
from utils.order_status import OrderStatusService, StatusError


def command(payment="CASH", **financial_changes):
    financial = {"tariff_version": "synthetic-v1", "products_bani": 3250,
                 "basis": "zone", "zone_id": "zone-one", **financial_changes}
    return CreateOrderCommand(client_operation_id="synthetic_financial_0001", order={
        "restaurant_id": "qa-restaurant", "customer_name": "Synthetic Customer",
        "customer_phone": "0700000000", "customer_address": "Synthetic address 123",
        "total_amount": 32.5, "payment_type": payment,
        "customer_latitude": 1.0, "customer_longitude": 1.0,
    }, financial=financial)


def grid(**changes):
    return {"contract_version": 1, "restaurant_id": "qa-restaurant", "version": "synthetic-v1",
            "currency": "RON", "approved": True,
            "zones": {"zone-one": {"restaurant_transport_bani": 1600, "courier_remuneration_bani": 975}},
            "outside": {"distance_rounding": "floor_km", "restaurant_rate_per_km_bani": 300,
                        "restaurant_minimum_bani": 4000, "courier_remuneration_bani": 1750}, **changes}


class Configuration:
    def __init__(self, tariff=None, enabled=True):
        self.tariff, self.enabled = grid() if tariff is None else tariff, enabled
        self.order_operation_settings = self.restaurant_tariff_versions = self

    async def find_one(self, query):
        assert query == {"_id": "order-finance-v1"}
        return {"enabled": self.enabled} if self.enabled is not None else None

    def find(self, query, projection):
        assert query == {"restaurant_id": "qa-restaurant", "version": "synthetic-v1"}
        assert projection == {"_id": 0}
        return self

    def limit(self, value):
        assert value == 2
        return self

    async def to_list(self, value):
        return [] if self.tariff == {} else [deepcopy(self.tariff)]


def quote(cmd=None, configuration=None, actor=None, zone="default"):
    cmd = cmd or command()
    detected = {"id": "zone-one"} if zone == "default" else zone
    return asyncio.run(quote_at_admission(configuration or Configuration(), cmd,
                       actor or {"role": "admin"}, "create:synthetic-financial", detected))


def order(snapshot=None):
    snap = snapshot or quote()
    return {"id": "synthetic-order", "order_number": "QA.1", "restaurant_id": "qa-restaurant",
            "restaurant_name": "Synthetic Restaurant", "customer_name": "Synthetic Customer",
            "customer_phone": "0700000000", "customer_address": "Synthetic address 123", "items": [],
            "status": "NEW", "preparation_status": "NEW", "order_version": 0,
            "payment_type": "CASH" if snap["collection_mode"] == "cash" else "CARD",
            "subtotal_amount": snap["products_bani"] / 100,
            "delivery_fee": snap["restaurant_transport_bani"] / 100,
            "total_amount": snap["client_collection_bani"] / 100,
            "financial_contract_version": 1, "financial": snap, "creation_operation_ref": snap["operation_ref"],
            "delivery_zone_id": snap["zone_id"], "delivery_zone_name": snap["zone_name"],
            "delivery_sector": snap["zone_sector"], "delivery_zone_level": snap["zone_level"], "zone": snap["zone_name"],
            "created_at": "2026-10-13T00:00:00+00:00"}


@pytest.mark.parametrize("invalid", [True, False, 1.2, "100", None, -1, 100_000_001])
def test_bani_require_bounded_integer(invalid):
    with pytest.raises(ValidationError):
        command(products_bani=invalid)


@pytest.mark.parametrize("amount,expected", [(0, 0), (32.5, 3250), (Decimal("0.01"), 1), (999999.99, 99999999)])
def test_exact_money_boundary(amount, expected):
    assert exact_bani(amount) == expected


@pytest.mark.parametrize("amount", [True, "1.00", 1.001, float("nan"), float("inf"), -0.01])
def test_money_precision_never_silently_rounded(amount):
    with pytest.raises(FinanceError):
        exact_bani(amount)


@pytest.mark.parametrize("payment,collection", [("CASH", 3250), ("CARD", 0)])
def test_cash_prepaid_separate_obligations_and_unknown_transfers(payment, collection):
    snap = quote(command(payment))
    assert snap["products_bani"] == 3250
    assert snap["client_collection_bani"] == snap["advance_required_bani"] == collection
    assert snap["restaurant_transport_bani"] == 1600 and snap["courier_remuneration_bani"] == 975
    assert [snap[k] for k in ("advance_paid_bani", "refund_due_bani", "refund_paid_bani")] == [None, None, None]


@pytest.mark.parametrize("enabled", [False, None, 1, "true"])
def test_financial_admission_default_disabled(enabled):
    with pytest.raises(FinanceError, match="nu este activat") as caught:
        quote(configuration=Configuration(enabled=enabled))
    assert caught.value.code == "FINANCIAL_NOT_ENABLED"


@pytest.mark.parametrize("tariff,code", [({}, "FINANCIAL_GRID_MISSING"),
    (grid(zones={}), "FINANCIAL_GRID_INCOMPLETE"),
    (grid(zones={"zone-one": {"restaurant_transport_bani": 1600}}), "FINANCIAL_GRID_INCOMPLETE"),
    (grid(approved=False), "FINANCIAL_GRID_NOT_APPROVED")])
def test_missing_tariff_is_not_zero_or_ten_percent(tariff, code):
    with pytest.raises(FinanceError) as caught:
        quote(configuration=Configuration(tariff=tariff))
    assert caught.value.code == code


def test_explicit_zero_tariff_is_valid_and_distinct_from_missing():
    snap = quote(configuration=Configuration(grid(zones={"zone-one": {
        "restaurant_transport_bani": 0, "courier_remuneration_bani": 0}})))
    assert snap["restaurant_transport_bani"] == snap["courier_remuneration_bani"] == 0


@pytest.mark.parametrize("distance,transport", [(0, 4000), (15300, 4500), (15999, 4500), (16000, 4800)])
def test_outside_uses_full_road_distance_floor_and_restaurant_specific_rule(distance, transport):
    cmd = command(basis="outside", zone_id=None, route_distance_m=distance, distance_evidence_ref="synthetic-road-proof")
    snap = quote(cmd, zone=None)
    assert snap["restaurant_transport_bani"] == transport and snap["courier_remuneration_bani"] == 1750
    with pytest.raises(FinanceError) as caught:
        quote(cmd, zone=None, actor={"role": "restaurant"})
    assert caught.value.code == "FINANCIAL_DISTANCE_AUTHORITY_REQUIRED"


def test_selected_tariff_can_change_without_repricing_admitted_snapshot():
    cmd = command()
    snap = quote(cmd)
    operation = {"_id": snap["operation_ref"], "financial_snapshot": snap}
    newer = quote(cmd, configuration=Configuration(grid(zones={"zone-one": {
        "restaurant_transport_bani": 2400, "courier_remuneration_bani": 1275}})))
    assert newer["courier_remuneration_bani"] == 1275
    assert admission_snapshot(operation, cmd).courier_remuneration_bani == 975


@pytest.mark.parametrize("path,value", [("courier_remuneration_bani", 976), ("snapshot_digest", "0" * 64),
                                      ("advance_paid_bani", 3250), ("contract_version", True)])
def test_corrupted_snapshot_fails_closed_every_consumer(path, value):
    doc = order()
    doc["financial"][path] = value
    with pytest.raises(FinanceError):
        order_financial_snapshot(doc)
    with pytest.raises(StatusError):
        OrderStatusService._delivery_totals(doc, {"total_earnings": 42.005, "total_deliveries": 8})
    warnings = set()
    clean = safe_order(doc, warnings)
    assert clean["financial"] is None and clean["read_actions_unavailable"] is True
    assert "ORDER_FINANCIAL_INVALID" in warnings
    assert clean["read_financial_invalid"] is True


def test_opted_in_item_prices_reject_excess_precision_without_inventing_discount_rule():
    raw = command().model_dump(mode="json")
    raw["order"]["items"] = [{"name": "Synthetic item", "quantity": 1, "price": 2.345}]
    with pytest.raises(FinanceError) as caught:
        quote(CreateOrderCommand.model_validate(raw))
    assert caught.value.code == "FINANCIAL_AMOUNT_INVALID"
    raw["order"]["items"][0]["price"] = 2.34
    assert quote(CreateOrderCommand.model_validate(raw))["products_bani"] == 3250


def test_model_and_safe_read_preserve_finance_without_exposing_unvalidated_fields():
    doc = order()
    assert Order(**doc).model_dump(mode="json")["financial"] == doc["financial"]
    warnings = set()
    clean = safe_order(doc, warnings)
    assert clean["financial"] == doc["financial"] and not clean["read_actions_unavailable"]
    doc["financial"]["private_extra"] = "MUST-NOT-LEAK"
    assert "MUST-NOT-LEAK" not in json.dumps(safe_order(doc, set()))


def test_missing_snapshot_cannot_fall_back_to_legacy_percentage():
    doc = order()
    del doc["financial"]
    with pytest.raises(StatusError):
        OrderStatusService._delivery_totals(doc, {"total_earnings": 42, "total_deliveries": 8})
    with pytest.raises(HTTPException) as caught:
        ensure_legacy_order(doc)
    assert caught.value.detail["code"] == "FINANCIAL_VERSIONED_OPERATION_REQUIRED"


def test_new_remuneration_and_legacy_aggregate_have_distinct_authorities():
    doc = order()
    driver = {"total_earnings": 42.005, "total_deliveries": 8}
    assert OrderStatusService._delivery_totals(doc, driver) == 9.75
    assert financial_earned_total(driver, 975) == 975
    assert driver["total_earnings"] == 42.005
    legacy = {"total_amount": 32.5}
    assert OrderStatusService._delivery_totals(legacy, driver) == 3.25


def test_legacy_intents_keep_their_original_serialized_shape_and_digest():
    old = CreateOrderCommand(client_operation_id="synthetic_legacy_0001", order={
        "restaurant_id": "qa-restaurant", "customer_name": "Synthetic Customer", "customer_phone": "0700000000",
        "customer_address": "Synthetic address 123", "total_amount": 32.5})
    assert "financial" not in old.model_dump(mode="json")
    payload = old.model_dump(mode="json", exclude={"client_operation_id"})
    encoded = json.dumps({"contract_version": 1, "type": "create", "target": None, "payload": payload},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    assert build_mutation_intent("actor", "create", None, old).payload_digest == sha256(encoded.encode()).hexdigest()
    assert "financial" not in Order(**{k: v for k, v in order().items()
        if k not in ("financial", "financial_contract_version", "order_version", "creation_operation_ref")}).model_dump(mode="json")
