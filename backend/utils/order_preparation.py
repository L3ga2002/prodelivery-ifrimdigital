"""Pure operational date and preparation parsing for order services.

Services supply their error factory and date parser so their existing local
entry points and error types remain intact. This module performs no writes.
"""

from datetime import datetime

from bson.int64 import Int64


def parse_operational_date(value, code, error_factory, *, datetime_type=datetime):
    try:
        if isinstance(value, datetime_type):
            return value
        if not isinstance(value, str) or not value:
            raise ValueError("Invalid timestamp")
        return datetime_type.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise error_factory(409, code, "Datele operationale necesita verificare.") from None


def parse_preparation(order, error_factory, date_parser, max_order_version):
    status = order["status"]
    prep = order.get("preparation_status")
    if prep is not None and (not isinstance(prep, str) or prep not in {"NEW", "PREPARING", "READY"}):
        raise error_factory(409, "ORDER_DATA_INVALID", "Pregatirea comenzii necesita verificare.")
    for field in ("preparation_started_at", "preparation_due_at", "preparation_ready_at"):
        if order.get(field) is not None:
            date_parser(order[field], "ORDER_DATA_INVALID")
    for field, maximum in (("preparation_time", 240), ("preparation_estimated_seconds", 14400),
                           ("preparation_actual_seconds", max_order_version),
                           ("preparation_delay_seconds", max_order_version)):
        value = order.get(field)
        if value is not None and (type(value) not in (int, Int64) or not 0 <= value <= maximum
                                  or field == "preparation_time" and value == 0):
            raise error_factory(409, "ORDER_DATA_INVALID", "Timerul comenzii necesita verificare.")
    if status in {"NEW", "PREPARING", "READY"}:
        if prep is not None and prep != status:
            raise error_factory(409, "ORDER_DATA_INVALID", "Pregatirea comenzii necesita verificare.")
        prep = status
    elif prep is None:
        prep = ("READY" if order.get("preparation_ready_at") is not None else
                "PREPARING" if order.get("preparation_started_at") is not None else "NEW")
    if (prep == "NEW" and any(order.get(field) is not None for field in (
            "preparation_started_at", "preparation_due_at", "preparation_ready_at"))
        or prep == "PREPARING" and order.get("preparation_ready_at") is not None):
        raise error_factory(409, "ORDER_DATA_INVALID", "Pregatirea comenzii necesita verificare.")
    return prep
