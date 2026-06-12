from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.order import OrderCreate, PreparationTime, UpdateOrderStatus  # noqa: E402
from routers.orders import (  # noqa: E402
    GENERIC_STATUS_ENDPOINT_STATUSES,
    _ensure_order_transition_allowed,
    _ensure_restaurant_accepts_new_orders,
    _order_audit_entry,
    build_status_update_payload,
)


def _valid_order_payload() -> dict:
    return {
        "restaurant_id": "rest-001",
        "customer_name": "Client Test",
        "customer_phone": "0712345678",
        "customer_address": "Str. Test 1, Bacau",
        "customer_latitude": 46.567,
        "customer_longitude": 26.913,
        "items": [{"name": "Pizza", "quantity": 1, "price": 30}],
        "subtotal_amount": 30,
        "delivery_fee": 0,
        "total_amount": 30,
        "payment_type": "CASH",
        "source": "S",
    }


def test_order_create_forbids_unknown_fields():
    payload = _valid_order_payload()
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        OrderCreate(**payload)


def test_order_status_rejects_unknown_status():
    with pytest.raises(ValidationError):
        UpdateOrderStatus(status="BROKEN")


def test_preparation_time_has_production_bounds():
    with pytest.raises(ValidationError):
        PreparationTime(preparation_time=0)

    with pytest.raises(ValidationError):
        PreparationTime(preparation_time=241)

    assert PreparationTime(preparation_time=30).preparation_time == 30


def test_order_state_machine_blocks_invalid_jump():
    with pytest.raises(HTTPException) as exc:
        _ensure_order_transition_allowed({"status": "NEW"}, "DELIVERED")

    assert exc.value.status_code == 409
    assert "NEW -> DELIVERED" in exc.value.detail


def test_order_state_machine_treats_same_status_as_duplicate():
    assert _ensure_order_transition_allowed({"status": "PICKED_UP"}, "PICKED_UP") is False


def test_generic_status_endpoint_excludes_dedicated_statuses():
    assert "PREPARING" not in GENERIC_STATUS_ENDPOINT_STATUSES
    assert "READY" not in GENERIC_STATUS_ENDPOINT_STATUSES
    assert "ASSIGNED" not in GENERIC_STATUS_ENDPOINT_STATUSES


def test_cancel_status_requires_reason_before_payload_is_built():
    with pytest.raises(HTTPException) as exc:
        build_status_update_payload(UpdateOrderStatus(status="CANCELLED"), {"role": "admin"})

    assert exc.value.status_code == 400
    assert "reason" in exc.value.detail.lower()


def test_restaurant_pause_or_closed_blocks_new_orders():
    with pytest.raises(HTTPException) as closed:
        _ensure_restaurant_accepts_new_orders({"closed_today": True, "accepting_orders": False})
    assert closed.value.status_code == 409

    with pytest.raises(HTTPException) as paused:
        _ensure_restaurant_accepts_new_orders({"accepting_orders": False, "pause_until": "2026-06-12T12:00:00+00:00"})
    assert paused.value.status_code == 409


def test_order_audit_entry_records_actor_and_action():
    entry = _order_audit_entry(
        "order.status_changed",
        {"user_id": "user-1", "role": "admin"},
        {"from_status": "ASSIGNED", "to_status": "ACCEPTED"},
    )

    assert entry["action"] == "order.status_changed"
    assert entry["performed_by"] == "user-1"
    assert entry["performed_by_role"] == "admin"
    assert entry["changes"]["to_status"] == "ACCEPTED"
