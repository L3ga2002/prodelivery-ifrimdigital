"""Role-bound read projection and cache handling for eight canonical GET routes.

No configuration imports, DB writes, ledger reads, or admission repricing.
The private snapshot/activity/custody/link validators run before project_order.
"""

import asyncio
from contextvars import ContextVar
import re
import math
import time

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from models.order_financial_reads import PublicOrderFinancial, AssignedDriverOrderFinancial, ReadContext


READ_DEADLINE = ContextVar("private_order_read_deadline", default=None)
NO_STORE = {"Cache-Control": "no-store"}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_AUDIT_ENTRIES = 10000
MAX_INCIDENTS = 50
PRIVATE_ORDER_FIELDS = frozenset(("creation_operation_ref", "remake_operation_ref",
    "problem_followup_operation_ref", "audit_trail"))
PRIVATE_HISTORY_FIELDS = frozenset(("financial_snapshot_digest", "courier_remuneration_bani"))
INCIDENT_TYPES = frozenset(("missing_product", "damaged_product", "pickup_blocked", "delivery_blocked", "other"))
OUTER_FIELDS = {
    "restaurant": ("id", "name", "address", "phone", "contact_name", "email", "latitude", "longitude",
        "location_source", "program", "is_active", "accepting_orders", "status", "closed_until", "schedule_settings"),
    "driver": ("id", "user_id", "name", "phone", "email", "first_name", "last_name", "birth_date", "gender", "cnp",
        "phone_verified", "vehicle_type", "email_verified", "is_active", "driver_status", "break_started_at",
        "break_until", "active_avatar_id", "avatar_url", "avatar_status", "latitude", "longitude", "current_order_id",
        "total_deliveries", "total_earnings", "financial_earned_bani", "punctuality_rate", "manual_ranking_score",
        "manual_rank_note", "manual_rank_updated_at", "manual_rank_updated_by", "joined_at", "account_disabled"),
    "user_contact": ("id", "name", "email", "phone", "first_name", "last_name", "birth_date", "gender", "cnp", "phone_verified"),
    "schedule": ("id", "driver_id", "week_start", "slots", "total_hours", "ranking_priority", "source", "force_override"),
    "avatar": ("id", "driver_id", "user_id", "status", "content_type", "size", "uploaded_by", "uploaded_by_role",
        "uploaded_at", "approved_at", "approved_by", "is_active", "is_deleted", "image_url", "rejected_at", "rejected_by", "moderation_note"),
    "driver_audit": ("id", "action", "performed_by", "performed_by_role", "entity_type", "entity_id", "created_at", "details"),
}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def failure(status=503, code="READ_UNAVAILABLE"):
    messages = {401: "Autentificarea este necesara.", 403: "Accesul la comenzi nu este autorizat.",
        404: "Comanda nu este disponibila.", 409: "Datele comenzii necesita verificare.",
        422: "Parametrii citirii sunt invalizi.", 503: "Citirea nu este disponibila. Reincearca actualizarea."}
    return HTTPException(status, {"code": code, "message": messages[status]}, headers=NO_STORE)


def valid_identifier(value):
    try:
        return (isinstance(value, str) and 1 <= len(value) <= 120 and value == value.strip()
            and len(value.encode("utf-8")) <= 480
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    except UnicodeError:
        return False


async def signed_read_actor(request: Request):
    # Lazy access to the existing decoder: import of this pure utility never
    # imports auth/database/dotenv or reads configured secrets.
    from auth import ACCESS_TOKEN_COOKIE, decode_token
    headers = request.headers
    if (len(headers.getlist("authorization")) > 1 or len(headers.getlist("cookie")) > 1
            or len(headers.getlist("X-Expected-Actor-ID")) > 1):
        raise failure(422, "INVALID_REQUEST")
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = headers.get("authorization", "")
        scheme, _, credential = auth.partition(" ")
        if scheme.lower() == "bearer":
            token = credential
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise failure(401, "AUTH_REQUIRED")
    try:
        payload = decode_token(token, "access")
    except HTTPException as error:
        if error.status_code in (401, 403):
            raise failure(error.status_code, "AUTH_REQUIRED" if error.status_code == 401 else "NOT_AUTHORIZED") from None
        raise failure() from None
    if not isinstance(payload, dict) or not valid_identifier(payload.get("user_id")):
        raise failure(401, "AUTH_REQUIRED")
    expiry = payload.get("exp")
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time():
        raise failure(401, "AUTH_REQUIRED")
    actor_id, role = payload["user_id"], payload.get("role")
    if payload.get("id", actor_id) != actor_id or role not in ("admin", "restaurant", "driver"):
        raise failure(403, "AUTH_CONTEXT_CHANGED")
    actor = {"id": actor_id, "user_id": actor_id, "role": role}
    for field, required in (("restaurant_id", role == "restaurant"), ("driver_id", role == "driver")):
        value = payload.get(field)
        if required and not valid_identifier(value) or value is not None and not valid_identifier(value):
            raise failure(403, "AUTH_CONTEXT_CHANGED")
        actor[field] = value
    expected = headers.get("X-Expected-Actor-ID")
    if expected is not None:
        if not valid_identifier(expected):
            raise failure(422, "INVALID_REQUEST")
        if expected != actor_id:
            raise failure(403, "AUTH_CONTEXT_CHANGED")
    return actor


class PrivateOrderReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            marker = READ_DEADLINE.set(asyncio.get_running_loop().time() + 8)
            try:
                if (len(request.scope.get("query_string", b"")) > 8192
                    or any(len(value) > 8192 for _, value in request.scope.get("headers", ()))
                    or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params)):
                    raise failure(422, "INVALID_REQUEST")
                async with asyncio.timeout_at(READ_DEADLINE.get()):
                    response = await handler(request)
                if not hasattr(response, "body") or len(response.body) > MAX_RESPONSE_BYTES:
                    raise failure()
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                error = failure(422, "INVALID_REQUEST")
            except HTTPException as caught:
                status = caught.status_code if caught.status_code in (401, 403, 404, 409, 422, 503) else 503
                detail = caught.detail
                code = detail.get("code") if isinstance(detail, dict) else None
                if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code):
                    code = {401: "AUTH_REQUIRED", 403: "NOT_AUTHORIZED", 404: "ORDER_NOT_FOUND",
                            409: "ORDER_ID_AMBIGUOUS", 422: "INVALID_REQUEST", 503: "READ_UNAVAILABLE"}[status]
                error = failure(status, code)
            except Exception:
                # Exception details may contain documents, credentials or query input.
                error = failure()
            finally:
                READ_DEADLINE.reset(marker)
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=NO_STORE)
        return private_handler


def private_read(router, path):
    def register(endpoint):
        router.add_api_route(path, endpoint, methods=["GET"], route_class_override=PrivateOrderReadRoute)
        return endpoint
    return register


def require_context(context):
    if (not isinstance(context, ReadContext) or not valid_identifier(context.actor_id)
        or context.role not in ("admin", "restaurant", "driver")
        or context.role == "restaurant" and not valid_identifier(context.restaurant_id)
        or context.role == "driver" and not valid_identifier(context.driver_id)):
        raise failure(403, "AUTH_CONTEXT_CHANGED")
    return context


def project_order(validated_order, context):
    """Project a safe_order result; full/private checks must already have run."""
    require_context(context)
    if any(validated_order.get(k) != value for k, value in context.scope.items()):
        raise failure(403, "AUTH_CONTEXT_CHANGED")
    result = dict(validated_order)
    if context.role == "admin":
        return result
    for name in PRIVATE_ORDER_FIELDS:
        result.pop(name, None)
    if "financial" in result or "financial_contract_version" in result:
        result.update(financial_read_contract_version=1, financial_read_visibility=context.visibility)
        if result.get("read_financial_invalid") is not True:
            model = AssignedDriverOrderFinancial if context.role == "driver" else PublicOrderFinancial
            full = result.get("financial")
            if not isinstance(full, dict):
                raise failure()
            result["financial"] = model.model_validate({k: full[k] for k in model.model_fields}).model_dump(mode="json")
    return result


def project_history(history, context):
    require_context(context)
    if context.role == "admin":
        return history
    return [{**entry, "changes": {k: v for k, v in entry["changes"].items()
                                  if k not in PRIVATE_HISTORY_FIELDS}} for entry in history]


def project_outer(document, kind):
    """Known bounded dashboard containers; never recurse through unknown objects."""
    import math
    from datetime import datetime
    def scalar(value):
        if value is None or type(value) is bool or isinstance(value, datetime):
            return value
        if isinstance(value, str) and len(value) <= 4000:
            return value
        if type(value) in (int, float) and math.isfinite(value):
            return value
        raise failure()
    result = {}
    for key in OUTER_FIELDS[kind]:
        if key not in document:
            continue
        value = document[key]
        if key in ("slots", "schedule_settings"):
            if not isinstance(value, dict) or any(day not in DAYS for day in value):
                raise failure()
            clean = {}
            for day, data in value.items():
                if key == "schedule_settings":
                    if not isinstance(data, dict):
                        raise failure()
                    clean[day] = {f: scalar(data[f]) for f in ("enabled", "open_time", "close_time") if f in data}
                else:
                    if not isinstance(data, list) or len(data) > 100 or any(not isinstance(slot, dict) for slot in data):
                        raise failure()
                    clean[day] = [{f: scalar(slot[f]) for f in ("start", "end", "added_by", "forced", "warning") if f in slot} for slot in data]
            result[key] = clean
        elif key == "details":
            # Existing driver-only audit is admin-only; it has a finite BSON cap
            # upstream and is not included in any non-admin response.
            result[key] = value
        else:
            result[key] = scalar(value)
    return result
