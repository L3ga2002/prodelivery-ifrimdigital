"""Bounded, tenant-scoped order reads. No writes or global ledger scans."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import logging
import math
import re

from bson import BSON, ObjectId, json_util
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from bson.errors import BSONError
from fastapi import HTTPException
from pymongo.errors import PyMongoError

from models.order import ORDER_STATUS_VALUES
from utils.order_assignment import MULTI_FIELDS
from utils.order_revision import MAX_ORDER_VERSION
from utils.order_finance import FinanceError, order_financial_snapshot
from utils.financial_activity import inspect_activity, read_activity_failures, unavailable_activity_read
from utils.custody_activity import inspect_custody, read_custody_failures, unavailable_custody_read, CustodyError
from models.order_financial_reads import ReadContext
from utils.order_financial_reads import (READ_DEADLINE, MAX_AUDIT_ENTRIES, MAX_INCIDENTS, INCIDENT_TYPES,
    project_order, project_history, require_context, valid_identifier)


logger = logging.getLogger(__name__)
READ_TIMEOUT_SECONDS = 8
MAX_TIME_MS = 3000
MAX_CURSOR_LENGTH = 4096
MAX_PK_JSON_LENGTH = 1024
MIN_BSON_DATE = datetime(1, 1, 1, tzinfo=timezone.utc)
MAX_BSON_DATE = datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
NO_STORE = {"Cache-Control": "no-store"}
DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?)?$"
)
UTC_FILTER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$")
TEXT_FIELDS = {
    "id": 120, "order_number": 160, "source": 12, "restaurant_id": 120,
    "restaurant_name": 160, "driver_id": 120, "driver_name": 160,
    "customer_name": 140, "customer_phone": 24, "customer_address": 300,
    "notes": 1000, "zone": 160, "delivery_zone_id": 120,
    "delivery_zone_name": 160, "delivery_sector": 80,
    "linked_problem_order_id": 120, "problem_type": 40, "problem_description": 1000,
    "cancelled_by": 120, "cancellation_reason": 500,
}
NUMBER_FIELDS = {
    "customer_latitude": (-90, 90), "customer_longitude": (-180, 180),
    "subtotal_amount": (0, 1000000), "delivery_fee": (0, 1000000),
    "total_amount": (0, 1000000),
}
INTEGER_FIELDS = {
    "order_version": MAX_ORDER_VERSION, "delivery_zone_level": 50,
    "preparation_time": 240, "preparation_estimated_seconds": 14400,
    "preparation_actual_seconds": MAX_ORDER_VERSION,
    "preparation_delay_seconds": MAX_ORDER_VERSION,
}
DATE_FIELDS = (
    "created_at", "updated_at", "preparation_started_at", "preparation_due_at",
    "preparation_ready_at", "assigned_at", "accepted_at", "picked_up_at",
    "delivered_at", "cancelled_at",
)
ENUM_FIELDS = {"status": ORDER_STATUS_VALUES, "preparation_status": ("NEW", "PREPARING", "READY"),
               "payment_type": ("CASH", "CARD")}
CHANGE_FIELDS = {
    "from_status", "to_status", "old_driver_id", "new_driver_id", "driver_id",
    "driver_name", "preparation_time", "preparation_status", "preparation_due_at",
    "from_preparation_status", "to_preparation_status",
    "preparation_estimated_seconds", "preparation_actual_seconds", "preparation_delay_seconds",
    "cancellation_reason", "customer_name", "customer_phone", "customer_address",
    "customer_latitude", "customer_longitude", "notes",
    "financial_snapshot_digest", "courier_remuneration_bani",
    "problem_followup_order_id", "linked_problem_order_id",
    "declared_unpaid_bani", "declaration_id", "approval_id", "financial_activity_status", "repayment_due_policy",
    "custody_status", "incident_id", "custody_event_id", "decision",
}
REMAKE_LINK_FIELDS = {"problem_followup_order_id": 120, "problem_followup_operation_ref": 128, "remake_operation_ref": 128}
CORRECTION_FIELDS = {"customer_name", "customer_phone", "customer_address",
                     "customer_latitude", "customer_longitude", "notes"}


def read_error(status, code):
    messages = {
        401: "Autentificarea este necesara.", 403: "Accesul la comenzi nu este autorizat.",
        404: "Comanda nu este disponibila.", 409: "Datele comenzii necesita verificare.",
        422: "Parametrii citirii sunt invalizi.", 503: "Citirea nu este disponibila. Reincearca actualizarea.",
    }
    return HTTPException(status, {"code": code, "message": messages[status]}, headers=NO_STORE)


def identifier(value, status=422, code="INVALID_REQUEST"):
    if not valid_identifier(value):
        raise read_error(status, code)
    return value


def integer(value, minimum, maximum):
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise read_error(422, "INVALID_REQUEST")
    return value


def safe_date(value):
    try:
        if isinstance(value, str) and len(value) <= 64 and DATE_RE.fullmatch(value):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _filter_date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not UTC_FILTER_RE.fullmatch(value):
        raise read_error(422, "INVALID_REQUEST")
    parsed = safe_date(value)
    if parsed is None:
        raise read_error(422, "INVALID_REQUEST")
    # Mongo dates are millisecond-granular. Ceil both inclusive/exclusive bounds.
    try:
        remainder = parsed.microsecond % 1000
        return parsed + timedelta(microseconds=1000 - remainder) if remainder else parsed
    except OverflowError:
        raise read_error(422, "INVALID_REQUEST") from None


def _iso(value):
    parsed = safe_date(value)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") if parsed else None


def _text(value, maximum, *, audit=False):
    if (not isinstance(value, str) or len(value) > maximum
        or any(ord(char) < 32 and char not in "\n\r\t" for char in value)
        or audit and ("<" in value or ">" in value)):
        return None
    return value


def _number(value, minimum, maximum, *, integral=False):
    if integral and type(value) not in (int, Int64):
        return None
    if isinstance(value, Decimal128):
        try:
            decimal = value.to_decimal()
            if not decimal.is_finite():
                return None
            value = float(decimal)
        except (ArithmeticError, ValueError, TypeError):
            return None
    if type(value) not in (int, Int64, float) or not minimum <= value <= maximum or not math.isfinite(value):
        return None
    return int(value) if integral else value


def safe_order(document, warnings, *, projected=False):
    """Internal full validation. HTTP callers must additionally project by context."""
    out = {}
    for field, maximum in TEXT_FIELDS.items():
        out[field] = _text(document.get(field), maximum)
    for field, bounds in NUMBER_FIELDS.items():
        out[field] = _number(document.get(field), *bounds)
    for field, maximum in INTEGER_FIELDS.items():
        out[field] = _number(document.get(field), 0, maximum, integral=True)
    for field, values in ENUM_FIELDS.items():
        value = document.get(field)
        out[field] = value if isinstance(value, str) and value in values else None
    for field in DATE_FIELDS:
        out[field] = _iso(document.get(field))
    has_revision = document.get("_read_has_revision", "order_version" in document)
    if not has_revision:
        out.pop("order_version")
    has_preparation_status = document.get("_read_has_preparation_status", "preparation_status" in document)
    if not has_preparation_status:
        out.pop("preparation_status")
    invalid_fields = False
    for name, maximum in REMAKE_LINK_FIELDS.items():
        if document.get("_read_has_" + name, name in document):
            out[name] = _text(document.get(name), maximum)
    if document.get("_read_has_has_problem_followup", "has_problem_followup" in document):
        flag = document.get("has_problem_followup")
        out["has_problem_followup"] = flag if type(flag) is bool else None
        if type(flag) is not bool:
            invalid_fields = True
            warnings.add("ORDER_FIELD_INVALID")
    remake_invalid = (
        any(document.get("_read_has_" + name, name in document) and not out.get(name) for name in REMAKE_LINK_FIELDS)
        or "remake_operation_ref" in out and not out.get("linked_problem_order_id")
        or "problem_followup_operation_ref" in out and (not out.get("problem_followup_order_id") or out.get("has_problem_followup") is not True)
        or "problem_followup_order_id" in out and "problem_followup_operation_ref" not in out
    )
    if remake_invalid:
        out["read_remake_invalid"] = True
        invalid_fields = True
        warnings.add("ORDER_FIELD_INVALID")
    for field, value in out.items():
        if value is None and document.get(field) is not None:
            warnings.add("ORDER_FIELD_INVALID")
            invalid_fields = True
    if document.get("_read_has_financial", "financial" in document or "financial_contract_version" in document):
        try:
            if not _fits_object(document.get("financial"), 8192):
                raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
            financial = order_financial_snapshot(document)
            out["financial"] = financial.model_dump(mode="json")
            out["financial_contract_version"] = 1
            out["creation_operation_ref"] = financial.operation_ref
        except FinanceError:
            out["financial"] = None
            out["financial_contract_version"] = None
            out["read_financial_invalid"] = True
            warnings.add("ORDER_FINANCIAL_INVALID")
            invalid_fields = True
    activity_present = "financial_activity" in document or "financial_activity_contract_version" in document
    if projected:
        activity_present = document.get("_read_has_financial_activity", activity_present)
    if activity_present:
        try:
            if not _fits_object(document.get("financial_activity"), 4096):
                raise FinanceError("FINANCIAL_ACTIVITY_INVALID")
            out["financial_activity"] = inspect_activity(document, projected=projected).public()
            out["financial_activity_contract_version"] = 1
        except FinanceError:
            out["financial_activity"] = None
            out["financial_activity_contract_version"] = None
            out["read_financial_activity_invalid"] = True
            warnings.add("ORDER_FINANCIAL_ACTIVITY_INVALID")
            invalid_fields = True
    if document.get("_read_has_custody", "custody_activity" in document or "custody_contract_version" in document) if projected else ("custody_activity" in document or "custody_contract_version" in document):
        try:
            if not _fits_object(document.get("custody_activity"), 8192):
                raise CustodyError("CUSTODY_INVALID")
            out["custody_activity"] = inspect_custody(document, projected=projected).public()
            out["custody_contract_version"] = 1
        except CustodyError:
            unavailable_custody_read(out)
            invalid_fields = True
            warnings.add("ORDER_CUSTODY_INVALID")
    for field in ("id", "restaurant_id", "driver_id"):
        if out[field] is not None:
            try:
                identifier(out[field])
            except HTTPException:
                out[field] = None
                invalid_fields = True
                warnings.add("ORDER_FIELD_INVALID")
    prep = out.get("preparation_status")
    status = out["status"]
    prep_invalid = (
        has_preparation_status and has_revision and prep is None
        or prep is not None and status in ("NEW", "PREPARING", "READY") and prep != status
        or prep == "NEW" and any(out[name] is not None for name in (
            "preparation_started_at", "preparation_due_at", "preparation_ready_at"))
        or prep == "PREPARING" and out["preparation_ready_at"] is not None
        or document.get("preparation_time") is not None and out["preparation_time"] == 0
        or (out["customer_latitude"] is None) != (out["customer_longitude"] is None)
    )
    if prep_invalid:
        invalid_fields = True
        warnings.add("ORDER_FIELD_INVALID")
    if out["created_at"] is None:
        warnings.add("ORDER_DATE_UNAVAILABLE")
    if out["status"] is None:
        warnings.add("ORDER_STATUS_UNAVAILABLE")
    if out["id"] is None or not out["id"].strip():
        out["id"] = None
        warnings.add("ORDER_ID_UNAVAILABLE")
    items = document.get("items")
    out["items"] = []
    if not isinstance(items, list):
        if items is not None:
            warnings.add("ORDER_FIELD_INVALID")
    else:
        for item in items[:200]:
            if not isinstance(item, dict):
                warnings.add("ORDER_FIELD_INVALID")
                continue
            clean = {"name": _text(item.get("name"), 140),
                     "quantity": _number(item.get("quantity"), 1, 100, integral=True),
                     "price": _number(item.get("price"), 0, 100000)}
            if any(value is None for value in clean.values()):
                warnings.add("ORDER_FIELD_INVALID")
            out["items"].append(clean)
        if len(items) > 200:
            warnings.add("ORDER_FIELD_INVALID")
    if document.get("_read_invalid"):
        warnings.add("ORDER_FIELD_INVALID")
    if document.get("_read_has_incident_summary", "incident_summary" in document):
        incidents = document.get("incident_summary")
        good = isinstance(incidents, list) and len(incidents) <= MAX_INCIDENTS
        if good:
            good = all(isinstance(i, dict) and valid_identifier(i.get("id"))
                       and isinstance(i.get("incident_type"), str) and i["incident_type"] in INCIDENT_TYPES for i in incidents)
        if not good or document.get("_read_incident_invalid"):
            out["incident_summary"] = None
            invalid_fields = True
            warnings.add("ORDER_FIELD_INVALID")
        else:
            out["incident_summary"] = [{"id": i["id"], "incident_type": i["incident_type"]} for i in incidents]
    multi = document.get("_read_multi_fields", [name for name in MULTI_FIELDS if name in document])
    for name in multi:
        if name in MULTI_FIELDS:
            out[name] = None
    if multi:
        warnings.add("ORDER_ASSIGNMENT_UNSUPPORTED")
    invalid_revision = has_revision and out.get("order_version") is None
    if invalid_revision:
        warnings.add("ORDER_VERSION_INVALID")
    out["read_actions_unavailable"] = bool(multi or invalid_revision or invalid_fields or document.get("_read_invalid")
        or out["status"] is None or out["id"] is None or out["restaurant_id"] is None
        or document.get("driver_id") is not None and out["driver_id"] is None)
    return out


def _fits_object(value, maximum):
    try:
        return isinstance(value, dict) and len(value) <= 200 and len(BSON.encode(value)) <= maximum
    except (ValueError, TypeError, OverflowError, RecursionError, BSONError):
        return False


def safe_history(entry, warnings):
    out = {"index": entry["index"], "id": _text(entry.get("id"), 120, audit=True),
           "action": _text(entry.get("action"), 120, audit=True),
           "performed_by": _text(entry.get("performed_by"), 120, audit=True),
           "performed_by_role": None, "created_at": _iso(entry.get("created_at")),
           "from_order_version": None, "to_order_version": None, "changes": {}}
    role = entry.get("performed_by_role")
    if isinstance(role, str) and role in ("admin", "restaurant", "driver", "system"):
        out["performed_by_role"] = role
    for name in ("from_order_version", "to_order_version"):
        out[name] = _number(entry.get(name), 0, MAX_ORDER_VERSION, integral=True)
    changes = entry.get("changes")
    if isinstance(changes, dict):
        for name in sorted(CHANGE_FIELDS):
            if name not in changes:
                continue
            value = changes[name]
            if value is None or type(value) is bool:
                out["changes"][name] = value
            elif isinstance(value, str):
                clean = _text(value, 1000, audit=True)
                if clean is not None:
                    out["changes"][name] = clean
                else:
                    warnings.add("HISTORY_FIELD_INVALID")
            elif type(value) in (int, Int64, float) or isinstance(value, Decimal128):
                clean = _number(value, -1e12, 1e12)
                if clean is not None:
                    out["changes"][name] = clean
                else:
                    warnings.add("HISTORY_FIELD_INVALID")
            else:
                warnings.add("HISTORY_FIELD_INVALID")
        fields = changes.get("fields")
        if isinstance(fields, list):
            approved = sorted({name for name in fields if isinstance(name, str) and name in CORRECTION_FIELDS})
            if approved:
                out["changes"]["fields"] = ", ".join(approved)
    if not out["created_at"]:
        warnings.add("HISTORY_DATE_UNAVAILABLE")
    if not out["action"] or entry.get("_invalid"):
        warnings.add("HISTORY_ENTRY_INVALID")
    if entry.get("_invalid_fields"):
        warnings.add("HISTORY_FIELD_INVALID")
    for name in ("id", "action", "performed_by", "performed_by_role", "from_order_version", "to_order_version"):
        if entry.get(name) is not None and out[name] is None:
            warnings.add("HISTORY_FIELD_INVALID")
    return out


def _scalar(expression, maximum=1000):
    return {"$cond": [
        {"$eq": [{"$type": expression}, "string"]},
        {"$cond": [{"$lte": [{"$strLenCP": expression}, maximum]}, expression, None]},
        {"$cond": [{"$eq": [{"$type": expression}, "date"]},
            {"$cond": [{"$and": [{"$gte": [expression, MIN_BSON_DATE]}, {"$lte": [expression, MAX_BSON_DATE]}]}, expression, None]},
            {"$cond": [{"$in": [{"$type": expression}, ["int", "long", "double", "decimal", "bool", "null"]]}, expression, None]}]},
    ]}


def _normalized_date(expression):
    valid_string = {"$cond": [{"$eq": [{"$type": expression}, "string"]},
                              {"$cond": [{"$lte": [{"$strLenCP": expression}, 64]},
                               {"$regexMatch": {"input": expression, "regex": DATE_RE.pattern}}, False]}, False]}
    return {"$cond": [{"$or": [{"$eq": [{"$type": expression}, "date"]}, valid_string]},
                       {"$convert": {"input": expression, "to": "date", "onError": None, "onNull": None}}, None]}


def _date_stages():
    return [
        {"$set": {"_read_date": _normalized_date("$created_at"),
                   "_read_id": {"$cond": [{"$eq": [{"$type": "$id"}, "string"]},
                       {"$cond": [{"$lte": [{"$strLenCP": "$id"}, 120]}, "$id", ""]}, ""]}}},
        {"$set": {"_read_date": {"$cond": [{"$and": [
            {"$gte": ["$_read_date", MIN_BSON_DATE]},
            {"$lte": ["$_read_date", MAX_BSON_DATE]},
        ]}, "$_read_date", None]}}},
    ]


def _order_projection(*, include_raw=False):
    fields = {name: _scalar("$" + name, maximum) for name, maximum in TEXT_FIELDS.items()}
    fields.update({name: _scalar("$" + name, 64) for name in DATE_FIELDS})
    fields.update({name: _scalar("$" + name) for name in (*NUMBER_FIELDS, *INTEGER_FIELDS, *ENUM_FIELDS)})
    for name, maximum in {**REMAKE_LINK_FIELDS, "has_problem_followup": 10}.items():
        fields[name] = _scalar("$" + name, maximum)
        fields["_read_has_" + name] = {"$ne": [{"$type": "$" + name}, "missing"]}
    fields["created_at"] = "$_read_date"
    fields["_read_has_revision"] = {"$ne": [{"$type": "$order_version"}, "missing"]}
    fields["_read_has_preparation_status"] = {"$ne": [{"$type": "$preparation_status"}, "missing"]}
    fields["_read_has_financial"] = {"$or": [
        {"$ne": [{"$type": "$financial"}, "missing"]},
        {"$ne": [{"$type": "$financial_contract_version"}, "missing"]},
    ]}
    fields["financial_contract_version"] = _scalar("$financial_contract_version")
    fields["creation_operation_ref"] = _scalar("$creation_operation_ref", 128)
    fields["financial"] = {"$cond": [{"$eq": [{"$type": "$financial"}, "object"]},
        {"$cond": [{"$lte": [{"$bsonSize": "$financial"}, 8192]}, "$financial", None]}, None]}
    fields["_read_has_financial_activity"] = {"$or": [
        {"$ne": [{"$type": "$financial_activity"}, "missing"]},
        {"$ne": [{"$type": "$financial_activity_contract_version"}, "missing"]}]}
    fields["financial_activity_contract_version"] = _scalar("$financial_activity_contract_version")
    fields["financial_activity"] = {"$cond": [{"$eq": [{"$type": "$financial_activity"}, "object"]},
        {"$cond": [{"$lte": [{"$bsonSize": "$financial_activity"}, 4096]}, "$financial_activity", None]}, None]}
    fields["_read_has_custody"] = {"$or": [{"$ne": [{"$type": "$custody_activity"}, "missing"]},
        {"$ne": [{"$type": "$custody_contract_version"}, "missing"]}]}
    fields["custody_contract_version"] = _scalar("$custody_contract_version")
    fields["custody_activity"] = {"$cond": [{"$eq": [{"$type": "$custody_activity"}, "object"]},
        {"$cond": [{"$lte": [{"$bsonSize": "$custody_activity"}, 8192]}, "$custody_activity", None]}, None]}
    fields["_read_custody_items"] = {"$cond": [{"$isArray": "$items"}, {"$cond": [
        {"$lte": [{"$bsonSize": {"items": "$items"}}, 65536]}, "$items", None]}, None]}
    fields["_read_multi_fields"] = {"$filter": {"input": [
        {"name": name, "present": {"$ne": [{"$type": "$" + name}, "missing"]}}
        for name in MULTI_FIELDS], "as": "field", "cond": "$$field.present"}}
    fields["_read_multi_fields"] = {"$map": {"input": fields["_read_multi_fields"], "as": "field", "in": "$$field.name"}}
    fields["items"] = {"$map": {"input": {"$slice": [{"$cond": [{"$isArray": "$items"}, "$items", []]}, 200]},
        "as": "item", "in": {"name": _scalar("$$item.name", 140),
                              "quantity": _scalar("$$item.quantity"), "price": _scalar("$$item.price")}}}
    audit_size = {"$size": {"$cond": [{"$isArray": "$audit_trail"}, "$audit_trail", []]}}
    incident_size = {"$size": {"$cond": [{"$isArray": "$incident_summary"}, "$incident_summary", []]}}
    fields["_read_has_incident_summary"] = {"$ne": [{"$type": "$incident_summary"}, "missing"]}
    fields["_read_incident_invalid"] = {"$or": [
        {"$not": [{"$in": [{"$type": "$incident_summary"}, ["missing", "array"]]}]},
        {"$gt": [incident_size, MAX_INCIDENTS]}]}
    fields["incident_summary"] = {"$cond": [{"$isArray": "$incident_summary"}, {"$cond": [
        {"$and": [{"$lte": [incident_size, MAX_INCIDENTS]}, {"$lte": [{"$bsonSize": {"v": "$incident_summary"}}, 65536]}]},
        {"$map": {"input": "$incident_summary", "as": "incident", "in": {
            "id": _scalar("$$incident.id", 120), "incident_type": _scalar("$$incident.incident_type", 40)}}}, None]}, None]}
    if include_raw:
        fields["_read_compat_raw"] = {"$cond": [
            {"$and": [{"$lte": [{"$bsonSize": "$$ROOT"}, 262144]}, {"$lte": [audit_size, MAX_AUDIT_ENTRIES]}]}, "$$ROOT", None]}
    # Flag malformed containers without sending their raw content to the API.
    fields["_read_invalid"] = {"$or": [
        *[{"$ne": [{"$type": "$" + field}, "missing"]} for field in (
            "read_error", "read_error_code", "read_financial_invalid", "read_remake_invalid",
            "read_custody_invalid", "read_financial_activity_invalid", "read_actions_unavailable")],
        {"$not": [{"$in": [{"$type": "$items"}, ["array", "missing", "null"]]}]},
        {"$gt": [{"$size": {"$cond": [{"$isArray": "$items"}, "$items", []]}}, 200]},
        {"$gt": [audit_size, MAX_AUDIT_ENTRIES]},
        {"$cond": [{"$eq": [{"$type": "$audit_trail"}, "missing"]}, False,
            {"$cond": [{"$isArray": "$audit_trail"}, {"$anyElementTrue": [{"$map": {
                "input": {"$slice": ["$audit_trail", MAX_AUDIT_ENTRIES]}, "as": "entry", "in": {"$ne": [{"$type": "$$entry"}, "object"]}}}]}, True]}]},
        *[{"$and": [{"$not": [{"$in": [{"$type": "$" + name}, ["missing", "null"]]}]},
                    {"$eq": [_scalar("$" + name, TEXT_FIELDS.get(name, 64 if name in DATE_FIELDS else 1000)), None]}]}
          for name in (*TEXT_FIELDS, *DATE_FIELDS, *NUMBER_FIELDS, *INTEGER_FIELDS, *ENUM_FIELDS, *REMAKE_LINK_FIELDS)],
    ]}
    return fields


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _binding(actor, filters):
    return sha256(_canonical([actor, filters]).encode("ascii")).hexdigest()


def _encode_cursor(document, binding):
    pk = document["_id"]
    if not isinstance(pk, (ObjectId, str, int, Int64)) or isinstance(pk, bool):
        raise read_error(503, "ORDER_KEY_UNSUPPORTED")
    if isinstance(pk, str) and len(pk) > 120:
        raise read_error(503, "ORDER_KEY_UNSUPPORTED")
    data = {"v": 1, "binding": binding, "date": _iso(document.get("_read_date")),
            "id": document["_read_id"], "pk": json_util.dumps(pk, json_options=json_util.CANONICAL_JSON_OPTIONS, ensure_ascii=False)}
    body = _canonical(data)
    # UTF-8 avoids multiplying supplementary code points into nested ASCII escapes.
    envelope = json.dumps({"data": data, "checksum": sha256(body.encode("ascii")).hexdigest()},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    cursor = base64.urlsafe_b64encode(envelope.encode("utf-8")).decode("ascii").rstrip("=")
    if len(data["pk"]) > MAX_PK_JSON_LENGTH or len(cursor) > MAX_CURSOR_LENGTH:
        raise read_error(503, "ORDER_KEY_UNSUPPORTED")
    return cursor


def _decode_cursor(value, binding):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_CURSOR_LENGTH or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError()
        envelope = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        if not isinstance(envelope, dict) or set(envelope) != {"data", "checksum"}:
            raise ValueError()
        data = envelope["data"]
        if not isinstance(data, dict) or set(data) != {"v", "binding", "date", "id", "pk"}:
            raise ValueError()
        digest = sha256(_canonical(data).encode("ascii")).hexdigest()
        if (type(data["v"]) is not int or data["v"] != 1 or data["binding"] != binding
            or not isinstance(envelope["checksum"], str) or not hmac.compare_digest(envelope["checksum"], digest)
            or not isinstance(data["id"], str) or len(data["id"]) > 120
            or not isinstance(data["pk"], str) or len(data["pk"]) > MAX_PK_JSON_LENGTH):
            raise ValueError()
        date = _filter_date(data["date"])
        if data["date"] is not None and _iso(date) != data["date"]:
            raise ValueError()
        pk = json_util.loads(data["pk"])
        if not isinstance(pk, (ObjectId, str, int, Int64)) or isinstance(pk, bool) or isinstance(pk, str) and len(pk) > 120:
            raise ValueError()
        if isinstance(pk, (int, Int64)) and not -(1 << 63) <= pk <= MAX_ORDER_VERSION:
            raise ValueError()
        return date, data["id"], pk
    except (ValueError, TypeError, KeyError, UnicodeError, HTTPException, OverflowError, RecursionError):
        raise read_error(422, "INVALID_CURSOR") from None


def _after_cursor(anchor):
    date, order_id, pk = anchor
    equal_date = {"$eq": ["$_read_date", {"$literal": date}]}
    equal_id = {"$eq": ["$_read_id", {"$literal": order_id}]}
    return {"$expr": {"$or": [
        {"$lt": ["$_read_date", {"$literal": date}]},
        {"$and": [equal_date, {"$lt": ["$_read_id", {"$literal": order_id}]}]},
        {"$and": [equal_date, equal_id, {"$lt": ["$_id", {"$literal": pk}]}]},
    ]}}


def _identity_projection(fields):
    projection = {"_id": 0}
    invalid = []
    for name in fields:
        value = "$" + name
        valid = {"$cond": [{"$eq": [{"$type": value}, "string"]}, {"$and": [
            {"$lte": [{"$strLenCP": value}, 120]}, {"$lte": [{"$strLenBytes": value}, 480]}]}, False]}
        projection[name] = {"$cond": [{"$eq": [{"$type": value}, "missing"]}, "$$REMOVE",
            {"$cond": [valid, value, None]}]}
        invalid.append({"$and": [{"$not": [{"$in": [{"$type": value}, ["missing", "null"]]}]}, {"$not": [valid]}]})
    projection["account_disabled"] = {"$cond": [{"$eq": [{"$type": "$account_disabled"}, "missing"]},
        "$$REMOVE", {"$cond": [{"$eq": [{"$type": "$account_disabled"}, "bool"]}, "$account_disabled", None]}]}
    projection["_read_identity_invalid"] = {"$or": invalid}
    return projection


class _ProofReadCollection:
    """Keep existing exact-ID proof validators on the same bounded cursor path."""
    def __init__(self, service, collection):
        self.service, self.collection = service, collection

    def aggregate(self, pipeline, **options):
        service, collection = self.service, self.collection
        class Result:
            async def to_list(self, length):
                return await service._aggregate(collection, pipeline, length)
        return Result()


class _ProofReads:
    def __init__(self, service):
        self.service = service

    def __getattr__(self, name):
        if name not in ("order_financial_events", "order_custody_events", "order_incidents"):
            raise AttributeError(name)
        return _ProofReadCollection(self.service, getattr(self.service.db, name))


class OrderReadService:
    def __init__(self, database):
        self.db = database
        self.proof_reads = _ProofReads(self)

    async def _aggregate(self, collection, pipeline, length):
        cursor = collection.aggregate(pipeline, maxTimeMS=MAX_TIME_MS, batchSize=length,
                                      allowDiskUse=False, collation={"locale": "simple"})
        try:
            return await cursor.to_list(length)
        finally:
            try:
                await asyncio.wait_for(cursor.close(), timeout=0.25)
            except (TimeoutError, PyMongoError):
                logger.warning("order_read_cursor_cleanup_unavailable")

    async def _scope(self, actor, expected):
        actor_id = identifier(actor.get("user_id") or actor.get("id"), 401, "AUTH_REQUIRED")
        if actor.get("user_id") and actor.get("id") and actor["user_id"] != actor["id"]:
            raise read_error(401, "AUTH_REQUIRED")
        if expected is not None:
            identifier(expected)
            if expected != actor_id:
                raise read_error(403, "AUTH_CONTEXT_CHANGED")
        users = await self._aggregate(self.db.users, [{"$match": {"id": actor_id}}, {"$limit": 2},
            {"$project": _identity_projection(("id", "role", "restaurant_id", "driver_id"))}], 2)
        if not users:
            raise read_error(401, "AUTH_REQUIRED")
        if len(users) != 1:
            raise read_error(403, "AUTH_CONTEXT_CHANGED")
        user = users[0]
        role = user.get("role")
        if (not _fits_object(user, 4096) or user.get("_read_identity_invalid") or not valid_identifier(user.get("id")) or user["id"] != actor_id
            or not isinstance(role, str) or role not in ("admin", "restaurant", "driver") or role != actor.get("role")
            or user.get("account_disabled", False) is not False
            or any(user.get(f) is not None and not valid_identifier(user[f]) for f in ("restaurant_id", "driver_id"))):
            raise read_error(403, "NOT_AUTHORIZED")
        scope = {}
        if role == "restaurant":
            tenant = identifier(user.get("restaurant_id"), 403, "NOT_AUTHORIZED")
            if actor.get("restaurant_id") != tenant:
                raise read_error(403, "AUTH_CONTEXT_CHANGED")
            scope["restaurant_id"] = tenant
        if role == "driver":
            links = await self._aggregate(self.db.drivers, [{"$match": {"user_id": actor_id}}, {"$limit": 2},
                {"$project": _identity_projection(("id", "user_id"))}], 2)
            if (len(links) != 1 or not _fits_object(links[0], 4096) or links[0].get("_read_identity_invalid") or links[0].get("account_disabled", False) is not False
                or links[0].get("user_id") != actor_id):
                raise read_error(403, "NOT_AUTHORIZED")
            driver = identifier(links[0].get("id"), 403, "NOT_AUTHORIZED")
            for declared in (user.get("driver_id"), actor.get("driver_id")):
                if declared is not None and declared != driver:
                    raise read_error(403, "AUTH_CONTEXT_CHANGED")
            scope["driver_id"] = driver
        return scope, [actor_id, role, scope]

    async def _bounded(self, operation):
        try:
            deadline = READ_DEADLINE.get()
            async with asyncio.timeout_at(deadline if deadline is not None else asyncio.get_running_loop().time() + READ_TIMEOUT_SECONDS):
                return await operation()
        except HTTPException:
            raise
        except Exception as error:
            # Never log exception text: driver errors can include raw documents.
            logger.warning("order_read_unavailable error_type=%s", type(error).__name__)
            raise read_error(503, "READ_UNAVAILABLE") from None

    async def authorize_read(self, actor, expected_actor_id=None):
        async def execute():
            if not isinstance(actor, dict):
                raise read_error(401, "AUTH_REQUIRED")
            if actor.get("role") == "driver" and not valid_identifier(actor.get("driver_id")):
                raise read_error(403, "AUTH_CONTEXT_CHANGED")
            scope, identity = await self._scope(actor, expected_actor_id)
            return ReadContext(identity[0], identity[1], scope.get("restaurant_id"), scope.get("driver_id"))
        return await self._bounded(execute)

    async def revalidate_read(self, context):
        require_context(context)
        current = await self.authorize_read({"id": context.actor_id, "role": context.role,
            "restaurant_id": context.restaurant_id, "driver_id": context.driver_id})
        if current != context:
            raise read_error(403, "AUTH_CONTEXT_CHANGED")

    async def load_orders(self, context, *, query=None, limit=100, sort=None, compatibility=False):
        require_context(context)
        if type(limit) is not int or not 1 <= limit <= 2000:
            raise read_error(422, "INVALID_REQUEST")
        target = dict(query or {})
        for key, value in context.scope.items():
            if key in target and target[key] != value:
                raise read_error(403, "NOT_AUTHORIZED")
            target[key] = value
        exact = {k: v for k, v in target.items() if k in ("id", "restaurant_id", "driver_id")}
        for value in exact.values():
            identifier(value)
        match = {**target, **({"$expr": {"$and": [{"$eq": ["$" + k, {"$literal": v}]} for k, v in exact.items()]}} if exact else {})}
        pipeline = [{"$match": match}]
        if sort:
            pipeline.append({"$sort": sort})
        pipeline += [{"$limit": limit}, *_date_stages(), {"$project": {**_order_projection(
            include_raw=compatibility and context.role == "admin"), "_id": 0}}]
        return await self._aggregate(self.db.orders, pipeline, limit)

    async def serialize_orders(self, documents, context, *, compatibility=False):
        require_context(context)
        warnings = set()
        values = [safe_order(doc, warnings, projected=True) for doc in documents]
        for index in await read_custody_failures(self.proof_reads, documents, projected=True):
            unavailable_custody_read(values[index])
        for index in await read_activity_failures(self.proof_reads, documents, projected=True):
            unavailable_activity_read(values[index])
            warnings.add("ORDER_FINANCIAL_ACTIVITY_INVALID")
        await self.revalidate_read(context)
        if compatibility and context.role == "admin":
            for index, document in enumerate(documents):
                raw = document.get("_read_compat_raw")
                if not isinstance(raw, dict):
                    raise read_error(503, "READ_UNAVAILABLE")
                full = {k: v for k, v in raw.items() if k != "_id"}
                full.update({k: v for k, v in values[index].items() if k.startswith(("financial", "custody", "read_")) or k == "creation_operation_ref"})
                values[index] = full
        if compatibility:
            # The existing pure-legacy remake classifier deliberately checks own
            # property presence. A generated false flag is not a stored protocol.
            signals = ("order_version", "financial", "financial_contract_version", "financial_activity",
                       "financial_activity_contract_version", "custody_activity", "custody_contract_version")
            for value in values:
                if value.get("read_actions_unavailable") is False and not any(k in value for k in signals):
                    value.pop("read_actions_unavailable")
        return [project_order(value, context) for value in values], warnings

    async def compatibility(self, actor, *, kind="all", identifier_value=None, expected_actor_id=None):
        async def execute():
            context = await self.authorize_read(actor, expected_actor_id)
            query, limit, sort = {}, 1000, None
            if kind in ("restaurant", "driver"):
                identifier(identifier_value)
                field = kind + "_id"
                if context.role != "admin" and (context.role != kind or context.scope.get(field) != identifier_value):
                    raise read_error(403, "NOT_AUTHORIZED")
                query[field], limit = identifier_value, 100
                if kind == "driver":
                    query["status"] = {"$nin": ["DELIVERED", "CANCELLED"]}
                else:
                    sort = {"created_at": -1}
            elif kind == "one":
                identifier(identifier_value)
                query, limit = {"id": identifier_value}, 2
            elif kind != "all":
                raise read_error(422, "INVALID_REQUEST")
            documents = await self.load_orders(context, query=query, limit=limit, sort=sort, compatibility=True)
            if kind == "one" and len(documents) != 1:
                raise read_error(404 if not documents else 409, "ORDER_NOT_FOUND" if not documents else "ORDER_ID_AMBIGUOUS")
            values, _ = await self.serialize_orders(documents, context, compatibility=True)
            return values[0] if kind == "one" else values
        return await self._bounded(execute)

    async def outer_documents(self, collection, query, fields, *, limit=2, sort=None, cap=65536):
        """Finite known outer containers; callers whitelist nested fields separately."""
        pipeline = [{"$match": query}]
        if sort:
            pipeline.append({"$sort": sort})
        payload = {field: "$" + field for field in fields}
        pipeline += [{"$limit": limit}, {"$project": {"_id": 0, "value": {
            "$cond": [{"$lte": [{"$bsonSize": "$$ROOT"}, cap]}, payload, None]}}}]
        rows = await self._aggregate(collection, pipeline, limit)
        if any(not _fits_object(row.get("value"), cap) for row in rows):
            raise read_error(503, "READ_UNAVAILABLE")
        return [row["value"] for row in rows]

    async def page(self, actor, *, expected_actor_id=None, view="active", status=None,
                   restaurant_id=None, driver_id=None, from_date=None, to_date=None, limit=25, cursor=None):
        if not isinstance(view, str) or view not in ("active", "history", "all"):
            raise read_error(422, "INVALID_REQUEST")
        if status is not None and (not isinstance(status, str) or status not in ORDER_STATUS_VALUES):
            raise read_error(422, "INVALID_REQUEST")
        for value in (restaurant_id, driver_id):
            if value is not None:
                identifier(value)
        limit = integer(limit, 1, 100)
        start, end = _filter_date(from_date), _filter_date(to_date)
        if start and end and start >= end:
            raise read_error(422, "INVALID_REQUEST")
        filters = {"view": view, "status": status, "restaurant_id": restaurant_id, "driver_id": driver_id,
                   "from_date": _iso(start), "to_date": _iso(end), "limit": limit}

        async def execute():
            context = await self.authorize_read(actor, expected_actor_id)
            scope = context.scope
            binding_actor = [context.actor_id, context.role, scope]
            query = dict(scope)
            for name, value in (("restaurant_id", restaurant_id), ("driver_id", driver_id)):
                if value is not None:
                    if name in scope and scope[name] != value:
                        raise read_error(403, "NOT_AUTHORIZED")
                    query[name] = value
            constraints = [query]
            if query:
                constraints.append({"$expr": {"$and": [
                    {"$eq": ["$" + name, {"$literal": value}]} for name, value in query.items()]}})
            if view == "active":
                constraints.append({"status": {"$nin": ["DELIVERED", "CANCELLED"]}})
            elif view == "history":
                constraints.append({"status": {"$in": ["DELIVERED", "CANCELLED"]}})
            if status is not None:
                constraints.append({"status": status})
            binding = _binding(binding_actor, filters)
            anchor = _decode_cursor(cursor, binding) if cursor is not None else None
            pipeline = [{"$match": {"$and": constraints}}, *_date_stages()]
            date_query = {}
            if start:
                date_query["$gte"] = start
            if end:
                date_query["$lt"] = end
            if date_query:
                pipeline.append({"$match": {"_read_date": date_query}})
            if anchor is not None:
                pipeline.append({"$match": _after_cursor(anchor)})
            pipeline += [{"$sort": {"_read_date": -1, "_read_id": -1, "_id": -1}}, {"$limit": limit + 1},
                         {"$project": {**_order_projection(), "_id": 1, "_read_date": 1, "_read_id": 1}}]
            documents = await self._aggregate(self.db.orders, pipeline, limit + 1)
            more = len(documents) > limit
            selected = documents[:limit]
            warnings = set()
            items = [safe_order(document, warnings, projected=True) for document in selected]
            for index in await read_custody_failures(self.proof_reads, selected, projected=True):
                unavailable_custody_read(items[index])
            for index in await read_activity_failures(self.proof_reads, selected, projected=True):
                unavailable_activity_read(items[index])
                warnings.add("ORDER_FINANCIAL_ACTIVITY_INVALID")
            ids = [item["id"] for item in items if item["id"] is not None]
            duplicates = {value for value in ids if ids.count(value) > 1}
            if duplicates:
                warnings.add("ORDER_ID_AMBIGUOUS")
                for item in items:
                    if item["id"] in duplicates:
                        item["read_actions_unavailable"] = True
            await self.revalidate_read(context)
            items = [project_order(item, context) for item in items]
            return {"items": items, "next_cursor": _encode_cursor(selected[-1], binding) if more else None,
                    "has_more": more, "limit": limit, "data_warnings": sorted(warnings)}
        return await self._bounded(execute)

    async def detail(self, actor, order_id, *, expected_actor_id=None, history_before=None, history_limit=25):
        identifier(order_id)
        limit = integer(history_limit, 1, 50)
        before = integer(history_before, 0, 2147483647) if history_before is not None else None

        async def execute():
            context = await self.authorize_read(actor, expected_actor_id)
            scope = context.scope
            size = {"$size": {"$cond": [{"$isArray": "$audit_trail"}, "$audit_trail", []]}}
            bounded_size = {"$cond": [{"$lte": [size, MAX_AUDIT_ENTRIES]}, size, 0]}
            end = {"$min": [before, bounded_size]} if before is not None else bounded_size
            start = {"$max": [0, {"$subtract": [end, limit]}]}
            history_fields = {name: _scalar("$$entry." + name, 120 if name != "created_at" else 64)
                for name in ("id", "action", "performed_by", "performed_by_role", "created_at", "from_order_version", "to_order_version")}
            history_fields.update({"index": "$$index", "_invalid": {"$ne": [{"$type": "$$entry"}, "object"]},
                "changes": {"$arrayToObject": {"$filter": {"input": [
                    {"k": name, "v": _scalar("$$entry.changes." + name),
                     "present": {"$and": [
                         {"$in": [{"$type": "$$entry.changes." + name}, ["string", "int", "long", "double", "decimal", "bool", "null"]]},
                         {"$or": [{"$eq": [{"$type": "$$entry.changes." + name}, "null"]},
                                  {"$ne": [_scalar("$$entry.changes." + name), None]}]}]}}
                    for name in sorted(CHANGE_FIELDS)] + [{"k": "fields", "v": {
                        "$filter": {"input": {"$slice": [{"$cond": [{"$isArray": "$$entry.changes.fields"}, "$$entry.changes.fields", []]}, 20]},
                            "as": "field", "cond": {"$in": ["$$field", sorted(CORRECTION_FIELDS)]}}},
                        "present": {"$isArray": "$$entry.changes.fields"}}],
                    "as": "change", "cond": "$$change.present"}}}})
            history_fields["changes"] = {"$arrayToObject": {"$map": {
                "input": history_fields["changes"]["$arrayToObject"], "as": "change",
                "in": {"k": "$$change.k", "v": "$$change.v"}}}}
            history_fields["_invalid_fields"] = {"$or": [
                {"$not": [{"$in": [{"$type": "$$entry.changes"}, ["object", "missing", "null"]]}]},
                *[{"$and": [{"$not": [{"$in": [{"$type": "$$entry." + name}, ["missing", "null"]]}]},
                            {"$eq": [_scalar("$$entry." + name, 64 if name == "created_at" else 120), None]}]}
                  for name in ("id", "action", "performed_by", "performed_by_role", "created_at", "from_order_version", "to_order_version")],
                *[{"$and": [{"$not": [{"$in": [{"$type": "$$entry.changes." + name}, ["missing", "null"]]}]},
                            {"$or": [
                                {"$not": [{"$in": [{"$type": "$$entry.changes." + name}, ["string", "int", "long", "double", "decimal", "bool"]]}]},
                                {"$eq": [_scalar("$$entry.changes." + name), None]}]}]} for name in sorted(CHANGE_FIELDS)],
            ]}
            target = {"id": order_id, **scope}
            pipeline = [{"$match": {**target, "$expr": {"$and": [
                {"$eq": ["$" + name, {"$literal": value}]} for name, value in target.items()]}}}, {"$limit": 2}, *_date_stages(),
                {"$project": {**_order_projection(), "_id": 0, "_history_start": start, "_history_end": end,
                    "_history_invalid": {"$or": [{"$gt": [size, MAX_AUDIT_ENTRIES]}, {"$not": [{"$in": [{"$type": "$audit_trail"}, ["array", "missing"]]}]}]},
                    "_history": {"$map": {"input": {"$range": [start, end]}, "as": "index", "in": {
                        "$let": {"vars": {"entry": {"$arrayElemAt": ["$audit_trail", "$$index"]}}, "in": history_fields}}}}}}]
            documents = await self._aggregate(self.db.orders, pipeline, 2)
            if not documents:
                raise read_error(404, "ORDER_NOT_FOUND")
            if len(documents) != 1:
                raise read_error(409, "ORDER_ID_AMBIGUOUS")
            document = documents[0]
            warnings = set()
            order = safe_order(document, warnings, projected=True)
            if await read_custody_failures(self.proof_reads, [document], projected=True):
                unavailable_custody_read(order)
            if await read_activity_failures(self.proof_reads, [document], projected=True):
                unavailable_activity_read(order)
                warnings.add("ORDER_FINANCIAL_ACTIVITY_INVALID")
            history = [safe_history(entry, warnings) for entry in reversed(document["_history"])]
            if document["_history_invalid"]:
                warnings.add("HISTORY_UNAVAILABLE")
            more = document["_history_start"] > 0
            await self.revalidate_read(context)
            public_envelope = {} if context.role == "admin" else {"read_contract_version": 1, "read_visibility": context.visibility}
            return {"order": project_order(order, context), "history": project_history(history, context), **public_envelope,
                    "next_history_before": document["_history_start"] if more else None,
                    "history_has_more": more, "data_warnings": sorted(warnings)}
        return await self._bounded(execute)
