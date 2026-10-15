"""Characterize the preparation contract shared by assignment and status.

Pure tests only: no database, application settings, or server lifecycle.
The existing service entry points remain the observable compatibility surface.
"""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from bson.int64 import Int64
import pytest

from utils import order_assignment, order_status


@pytest.fixture(params=[order_assignment, order_status], ids=["assignment", "status"])
def service(request):
    return request.param


def assert_invalid(service, order, message):
    original = deepcopy(order)
    error_type = (order_assignment.AssignmentError if service is order_assignment
                  else order_status.StatusError)
    with pytest.raises(error_type) as caught:
        service._preparation(order)
    assert type(caught.value) is error_type
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409, "ORDER_DATA_INVALID", message,
    )
    assert order == original


@pytest.mark.parametrize("order,expected", [
    ({"status": "NEW"}, "NEW"),
    ({"status": "PREPARING"}, "PREPARING"),
    ({"status": "READY"}, "READY"),
    ({"status": "NEW", "preparation_status": None}, "NEW"),
    ({"status": "ASSIGNED"}, "NEW"),
    ({"status": "ACCEPTED", "preparation_status": None,
      "preparation_started_at": "2026-10-11T00:00:00Z"}, "PREPARING"),
    ({"status": "ASSIGNED", "preparation_ready_at": "2026-10-11T00:01:00Z"}, "READY"),
    ({"status": "PICKED_UP", "preparation_status": "READY"}, "READY"),
    ({"status": "ASSIGNED", "preparation_status": "PREPARING"}, "PREPARING"),
    ({"status": "PREPARING", "preparation_status": "PREPARING",
      "preparation_started_at": datetime(2026, 10, 11),
      "preparation_due_at": datetime(2026, 10, 11, tzinfo=timezone.utc)}, "PREPARING"),
    ({"status": "READY", "preparation_status": "READY",
      "preparation_started_at": "2026-10-11",
      "preparation_ready_at": "2026-10-11T00:01:00+03:00"}, "READY"),
])
def test_preparation_inference_preserves_legacy_values_without_mutating_order(service, order, expected):
    original = deepcopy(order)
    assert service._preparation(order) == expected
    assert order == original


@pytest.mark.parametrize("change", [
    {"preparation_status": True}, {"preparation_status": []},
    {"preparation_status": "unknown"}, {"preparation_status": "ready"},
    {"status": "NEW", "preparation_status": "READY"},
    {"status": "READY", "preparation_status": "NEW"},
    {"status": "NEW", "preparation_started_at": "2026-10-11T00:00:00Z"},
    {"status": "NEW", "preparation_due_at": "2026-10-11T00:00:00Z"},
    {"status": "NEW", "preparation_ready_at": "2026-10-11T00:00:00Z"},
    {"status": "PREPARING", "preparation_ready_at": "2026-10-11T00:00:00Z"},
    {"status": "ASSIGNED", "preparation_status": "PREPARING",
     "preparation_ready_at": "2026-10-11T00:00:00Z"},
])
def test_conflicting_or_malformed_preparation_keeps_service_error(service, change):
    assert_invalid(service, {"status": "ASSIGNED", **change},
                   "Pregatirea comenzii necesita verificare.")


@pytest.mark.parametrize("field,minimum,maximum", [
    ("preparation_time", 1, 240),
    ("preparation_estimated_seconds", 0, 14400),
    ("preparation_actual_seconds", 0, 9223372036854775807),
    ("preparation_delay_seconds", 0, 9223372036854775807),
])
def test_timer_exact_int_and_bson_int64_edges(service, field, minimum, maximum):
    for value in (None, minimum, maximum, Int64(minimum), Int64(maximum)):
        order = {"status": "READY", field: value}
        original = deepcopy(order)
        assert service._preparation(order) == "READY"
        assert order == original
        assert type(order[field]) is type(value)
    for value in (minimum - 1, maximum + 1, Int64(minimum - 1), Int64(maximum + 1)):
        assert_invalid(service, {"status": "READY", field: value},
                       "Timerul comenzii necesita verificare.")


@pytest.mark.parametrize("field", [
    "preparation_time", "preparation_estimated_seconds",
    "preparation_actual_seconds", "preparation_delay_seconds",
])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", [1], Decimal(1)])
def test_timer_never_coerces_boolean_or_non_integer_values(service, field, value):
    assert_invalid(service, {"status": "READY", field: value},
                   "Timerul comenzii necesita verificare.")


def test_timer_rejects_arbitrary_integer_subclasses(service):
    class CustomInt(int):
        pass

    assert_invalid(service, {"status": "READY", "preparation_actual_seconds": CustomInt(1)},
                   "Timerul comenzii necesita verificare.")


@pytest.mark.parametrize("field", [
    "preparation_started_at", "preparation_due_at", "preparation_ready_at",
])
@pytest.mark.parametrize("value", ["", "not-a-date", True, 1, [], {}])
def test_invalid_timestamp_keeps_date_error_message(service, field, value):
    assert_invalid(service, {"status": "READY", field: value},
                   "Datele operationale necesita verificare.")


@pytest.mark.parametrize("value", [
    datetime(2026, 10, 11), datetime(2026, 10, 11, tzinfo=timezone.utc),
])
def test_native_datetime_is_returned_without_normalization(service, value):
    assert service._date(value, "DRIVER_DATA_INVALID") is value


@pytest.mark.parametrize("value,expected", [
    ("2026-10-11", datetime(2026, 10, 11)),
    ("2026-10-11T00:01:00", datetime(2026, 10, 11, 0, 1)),
    ("2026-10-11T00:01:00Z", datetime(2026, 10, 11, 0, 1, tzinfo=timezone.utc)),
])
def test_iso_timestamp_acceptance_is_preserved(service, value, expected):
    assert service._date(value, "DRIVER_DATA_INVALID") == expected


@pytest.mark.parametrize("value", [None, "", " ", False, 0, [], {}, "2026-13-11"])
def test_date_preserves_callers_error_code_and_suppresses_parser_cause(service, value):
    error_type = (order_assignment.AssignmentError if service is order_assignment
                  else order_status.StatusError)
    with pytest.raises(error_type) as caught:
        service._date(value, "DRIVER_DATA_INVALID")
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409, "DRIVER_DATA_INVALID", "Datele operationale necesita verificare.",
    )
    assert caught.value.__suppress_context__ is True
    assert caught.value.__cause__ is None


def test_preparation_keeps_call_time_date_lookup(service, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_date", lambda value, code: calls.append((value, code)))
    order = {"status": "READY", "preparation_started_at": "start",
             "preparation_due_at": "due", "preparation_ready_at": "ready"}
    assert service._preparation(order) == "READY"
    assert calls == [("start", "ORDER_DATA_INVALID"), ("due", "ORDER_DATA_INVALID"),
                     ("ready", "ORDER_DATA_INVALID")]


def test_error_factory_is_resolved_from_each_service_at_call_time(service, monkeypatch):
    class CustomError(Exception):
        pass

    error = CustomError("local service error")
    calls = []

    def error_factory(status, code, message):
        calls.append((status, code, message))
        return error

    monkeypatch.setattr(service, "_error", error_factory)
    with pytest.raises(CustomError) as preparation:
        service._preparation({"status": "NEW", "preparation_status": False})
    with pytest.raises(CustomError) as timestamp:
        service._date(False, "CUSTOM_DATE_CODE")
    assert preparation.value is error and timestamp.value is error
    assert calls == [
        (409, "ORDER_DATA_INVALID", "Pregatirea comenzii necesita verificare."),
        (409, "CUSTOM_DATE_CODE", "Datele operationale necesita verificare."),
    ]


def test_revision_limit_remains_owned_by_each_service(service, monkeypatch):
    monkeypatch.setattr(service, "MAX_ORDER_VERSION", 9)
    assert service._preparation({"status": "READY", "preparation_actual_seconds": Int64(9)}) == "READY"
    assert_invalid(service, {"status": "READY", "preparation_actual_seconds": Int64(10)},
                   "Timerul comenzii necesita verificare.")


def test_date_keeps_service_local_datetime_dependency(service, monkeypatch):
    parsed = object()

    class DateParser:
        @staticmethod
        def fromisoformat(value):
            assert value == "2026-10-11T00:00:00+00:00"
            return parsed

    monkeypatch.setattr(service, "datetime", DateParser)
    assert service._date("2026-10-11T00:00:00Z", "ORDER_DATA_INVALID") is parsed
