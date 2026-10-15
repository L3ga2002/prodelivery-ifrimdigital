"""Additive recoverable operations; legacy order routes are unchanged."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from auth import get_current_user
from database import db
from models.order_mutation import AssignOrderCommand, CloseFinancialCreation, CreateOrderCommand, EditOrderCommand, OperationCommand, StatusOrderCommand
from utils.order_assignment import AssignmentError, DEADLINE_SECONDS, OrderAssignmentService
from utils.order_creation import CreationError, OrderCreationService, VerifiedFinancialContext
from utils.order_editing import EditingError, OrderEditingService
from utils.order_status import OrderStatusService, StatusError
from models.operational_reporting import IncidentCommand, OperationalCommand
from utils.operational_reporting import OperationalReportingService, ReportingError
from models.order_preparation_operations import PreparingOperationCommand, ReadyOperationCommand
from utils.order_preparation_operations import OrderPreparationService, PreparationError
from models.order_remakes import CloseFinancialRemake, RemakeCommand
from utils.order_remakes import OrderRemakeService
from models.order_financial_events import FinancialEventCommand
from utils.order_financial_events import OrderFinancialEventService
from models.order_custody import CustodyCommand
from utils.order_custody import OrderCustodyService
from models.order_finance_preview import CreateFinancePreview, RemakeFinancePreview
from utils.order_finance_preview import OrderFinancePreviewService


class PrivateOperationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                # Framework errors otherwise echo invalid customer input/body.
                return JSONResponse({"detail": {"code": "INVALID_REQUEST", "message": "Datele cererii sunt invalide."}},
                                    status_code=422, headers={"Cache-Control": "no-store"})
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise

        return private_handler


router = APIRouter(prefix="/orders/operations", tags=["order operations"], route_class=PrivateOperationRoute)


class FinancePreviewRoute(PrivateOperationRoute):
    """Bound authentication, input reading and failures only on the new routes."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded_handler(request):
            try:
                async with asyncio.timeout(8):
                    if len(request.scope.get("query_string", b"")) > 1024:
                        raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cerere invalida."})
                    return await handler(request)
            except HTTPException as exc:
                detail = exc.detail
                if not isinstance(detail, dict) or not isinstance(detail.get("code"), str):
                    detail = {"code": "AUTH_REQUIRED" if exc.status_code == 401 else "INVALID_REQUEST",
                              "message": "Accesul la previzualizare nu este disponibil."}
                return JSONResponse({"detail": detail}, status_code=exc.status_code,
                    headers={**(exc.headers or {}), "Cache-Control": "no-store"})
            except Exception:
                # Never return configuration, validation input, database errors or
                # customer fields. This is scoped to F1, not legacy operations.
                return JSONResponse({"detail": {"code": "FINANCIAL_PREVIEW_UNAVAILABLE",
                    "message": "Previzualizarea nu este disponibila."}}, status_code=503,
                    headers={"Cache-Control": "no-store"})

        return bounded_handler


finance_router = APIRouter(prefix="/finance", route_class=FinancePreviewRoute)


def _finance_service(*, quote=False):
    if not quote:
        return OrderFinancePreviewService(db)
    try:
        # Existing configured material, explicitly injected; no new key/env/setup.
        # Import lazily so historical router test doubles need no new auth API.
        from auth import get_jwt_secret
        key = get_jwt_secret()
    except (KeyError, TypeError, ValueError, ImportError):
        raise HTTPException(503, detail={"code": "FINANCIAL_PREVIEW_KEY_UNAVAILABLE",
            "message": "Previzualizarea nu este disponibila."}) from None
    return OrderFinancePreviewService(db, signing_key=key)


def _finance_query(request, *, restaurant=False):
    expected = ["restaurant_id"] if restaurant else []
    if (sorted(key for key, _ in request.query_params.multi_items()) != expected
            or len(request.headers.getlist("X-Expected-Actor-ID")) != 1):
        raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Parametri invalizi."})


async def _finance_actor(request: Request):
    # Legacy get_current_user hydrates the current role/tenant, losing the signed
    # session context. F1 must compare that context with bounded current reads.
    from auth import ACCESS_TOKEN_COOKIE, decode_token, security
    if (len(request.headers.getlist("authorization")) > 1
            or sum(len(value) for value in request.headers.getlist("cookie")) > 8192
            or sum(len(value) for value in request.headers.getlist("authorization")) > 8192):
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Autentificarea este necesara."})
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        credentials = await security(request)
        token = credentials.credentials if credentials else None
    if not isinstance(token, str) or not 1 <= len(token) <= 8192:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Autentificarea este necesara."})
    payload = decode_token(token, "access")
    identity = payload.get("user_id")
    if (type(payload.get("exp")) not in (int, float)
            or not isinstance(identity, str) or not 1 <= len(identity) <= 120 or identity != identity.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in identity)):
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Autentificarea este necesara."})
    actor = {"id": identity, "user_id": identity, "role": payload.get("role"),
             "restaurant_id": payload.get("restaurant_id")}
    _remake_actor_context(actor, request.headers.get("X-Expected-Actor-ID"))
    try:
        return await _finance_service().authenticate(actor)
    except CreationError as exc:
        raise _http_error(exc) from None


async def _finance_body(request, model):
    size, chunks = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > 65536:
            raise HTTPException(413, detail={"code": "REQUEST_TOO_LARGE", "message": "Cererea este prea mare."})
        chunks.append(chunk)
    try:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = value
            return result
        def finite_constant(value):
            raise ValueError("Non-finite JSON value")
        value = json.loads(b"".join(chunks), object_pairs_hook=unique_pairs, parse_constant=finite_constant)
        return model.model_validate(value)
    except (ValidationError, ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Datele cererii sunt invalide."}) from None


@finance_router.get("/capabilities")
async def finance_capabilities(request: Request, restaurant_id: str, actor: dict = Depends(_finance_actor),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _finance_query(request, restaurant=True)
    try:
        return await _finance_service().capabilities(restaurant_id, actor)
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.get("/tariffs")
async def finance_tariffs(request: Request, restaurant_id: str, actor: dict = Depends(_finance_actor),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _finance_query(request, restaurant=True)
    try:
        return await _finance_service().tariffs(restaurant_id, actor)
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/quote/create")
async def finance_quote_create(request: Request, actor: dict = Depends(_finance_actor),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _finance_query(request)
    command = await _finance_body(request, CreateFinancePreview)
    try:
        return await _finance_service(quote=True).quote_create(command, actor)
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/quote/remake/{parent_id}")
async def finance_quote_remake(parent_id: str, request: Request, actor: dict = Depends(_finance_actor),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _finance_query(request)
    command = await _finance_body(request, RemakeFinancePreview)
    try:
        return await _finance_service(quote=True).quote_remake(parent_id, command, actor)
    except CreationError as exc:
        raise _http_error(exc) from None


def _finance_creation_context(request, actor, *, mutation=False, operation_id=None):
    _finance_query(request)
    if actor.get("role") != "admin":
        raise HTTPException(403, detail={"code": "NOT_AUTHORIZED", "message": "Nu ai acces la aceasta operatie."})
    if mutation and (len(request.headers.getlist("content-type")) != 1
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
        raise HTTPException(415, detail={"code": "JSON_REQUIRED", "message": "Cererea necesita JSON."})
    if operation_id is not None:
        try:
            OperationCommand(client_operation_id=operation_id)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."}) from None
    return VerifiedFinancialContext(actor.get("user_id") or actor.get("id"), actor["role"], actor.get("restaurant_id"))


@finance_router.post("/create")
async def finance_confirmed_create(request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_creation_context(request, actor, mutation=True)
    command = await _finance_body(request, CreateOrderCommand)
    if command.quote_confirmation is None:
        raise HTTPException(422, detail={"code": "QUOTE_CONFIRMATION_REQUIRED", "message": "Confirma cotatia."})
    try:
        return _response(await OrderCreationService(db).create(command, actor, financial_context=context,
            signing_key=lambda: _finance_service(quote=True).signing_key))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.get("/create/{client_operation_id}")
async def finance_creation_lookup(client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_creation_context(request, actor, operation_id=client_operation_id)
    try:
        return _response(await OrderCreationService(db).lookup(client_operation_id, actor, financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/create/{client_operation_id}/resume")
async def finance_creation_resume(client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    # Empty-body resume needs only the mandatory custom header for preflight;
    # shared recoveryTransport deliberately sends no JSON Content-Type here.
    context = _finance_creation_context(request, actor, operation_id=client_operation_id)
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    try:
        return _response(await OrderCreationService(db).resume(client_operation_id, actor, financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/create/{client_operation_id}/close")
async def finance_creation_close(client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_creation_context(request, actor, mutation=True, operation_id=client_operation_id)
    close = await _finance_body(request, CloseFinancialCreation)
    try:
        return _response(await OrderCreationService(db).close_financial(
            client_operation_id, close, actor, financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


def _finance_remake_context(request, actor, *, mutation=False, operation_id=None):
    _finance_query(request)
    _remake_actor_context(actor, request.headers.get("X-Expected-Actor-ID"))
    if mutation and (len(request.headers.getlist("content-type")) != 1
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
        raise HTTPException(415, detail={"code": "JSON_REQUIRED", "message": "Cererea necesita JSON."})
    if operation_id is not None:
        try:
            OperationCommand(client_operation_id=operation_id)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."}) from None
    return VerifiedFinancialContext(actor.get("user_id") or actor.get("id"), actor["role"], actor.get("restaurant_id"))


@finance_router.get("/remake-parent/{parent_id}")
async def finance_remake_parent(parent_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor)
    try:
        return await OrderRemakeService(db).parent_context(parent_id, actor, financial_context=context)
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/remake/{parent_id}")
async def finance_remake_submit(parent_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor, mutation=True)
    command = await _finance_body(request, RemakeCommand)
    if command.quote_confirmation is None:
        raise HTTPException(422, detail={"code": "QUOTE_CONFIRMATION_REQUIRED", "message": "Confirma cotatia."})
    try:
        return _response(await OrderRemakeService(db).submit(parent_id, command, actor, financial_context=context,
            signing_key=lambda: _finance_service(quote=True).signing_key))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.get("/remake/{parent_id}/{client_operation_id}")
async def finance_remake_lookup(parent_id: str, client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor, operation_id=client_operation_id)
    try:
        return _response(await OrderRemakeService(db).lookup(parent_id, client_operation_id, actor, financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/remake/{parent_id}/{client_operation_id}/resume")
async def finance_remake_resume(parent_id: str, client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor, operation_id=client_operation_id)
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    try:
        return _response(await OrderRemakeService(db).resume(parent_id, client_operation_id, actor, financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.post("/remake/{parent_id}/{client_operation_id}/close")
async def finance_remake_close(parent_id: str, client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor, mutation=True, operation_id=client_operation_id)
    close = await _finance_body(request, CloseFinancialRemake)
    try:
        return _response(await OrderRemakeService(db).close_financial(parent_id, client_operation_id, close, actor,
            financial_context=context))
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.get("/remake/{parent_id}/{client_operation_id}/readback")
async def finance_remake_readback(parent_id: str, client_operation_id: str, request: Request, actor: dict = Depends(_finance_actor)):
    context = _finance_remake_context(request, actor, operation_id=client_operation_id)
    try:
        return await OrderRemakeService(db).readback(parent_id, client_operation_id, actor, financial_context=context)
    except CreationError as exc:
        raise _http_error(exc) from None


@finance_router.api_route("", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"], include_in_schema=False)
@finance_router.api_route("/{unknown:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"], include_in_schema=False)
async def finance_unknown_route(unknown: str = ""):
    known = unknown in {"capabilities", "tariffs", "quote/create", "create"} or unknown.startswith(("quote/remake/", "create/", "remake/", "remake-parent/"))
    return JSONResponse({"detail": {"code": "METHOD_NOT_ALLOWED" if known else "NOT_FOUND",
        "message": "Ruta nu este disponibila."}}, status_code=405 if known else 404,
        headers={"Cache-Control": "no-store"})


router.include_router(finance_router)


@router.get("/custody/capabilities")
async def custody_capabilities(actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderCustodyService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except StatusError as exc:
        raise _http_error(exc) from None


@router.post("/custody/{order_id}")
async def create_custody(order_id: str, command: CustodyCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderCustodyService(db).submit(order_id, command, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


@router.get("/custody/{order_id}/{client_operation_id}")
async def lookup_custody(order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderCustodyService(db).lookup(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


@router.post("/custody/{order_id}/{client_operation_id}/resume")
async def resume_custody(order_id: str, client_operation_id: str, request: Request,
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderCustodyService(db).resume(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


@router.get("/financial-event/capabilities")
async def financial_event_capabilities(actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderFinancialEventService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except StatusError as exc:
        raise _http_error(exc) from None


@router.post("/financial-event/{order_id}")
async def create_financial_event(order_id: str, command: FinancialEventCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderFinancialEventService(db).submit(order_id, command, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


@router.get("/financial-event/{order_id}/{client_operation_id}")
async def lookup_financial_event(order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderFinancialEventService(db).lookup(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


@router.post("/financial-event/{order_id}/{client_operation_id}/resume")
async def resume_financial_event(order_id: str, client_operation_id: str, request: Request,
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderFinancialEventService(db).resume(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from None


def _remake_actor_context(actor, expected_actor_id):
    if expected_actor_id is None:
        raise HTTPException(409, detail={"code": "EXPECTED_ACTOR_REQUIRED", "message": "Identitatea sesiunii trebuie confirmata."})
    _assign_actor_context(actor, expected_actor_id)


@router.get("/remake/capabilities")
async def remake_capabilities(actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderRemakeService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except CreationError as error:
        raise _http_error(error) from None


@router.post("/remake/{order_id}")
async def create_recoverable_remake(order_id: str, command: RemakeCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderRemakeService(db).submit(order_id, command, actor))
    except CreationError as error:
        raise _http_error(error) from None


@router.get("/remake/{order_id}/{client_operation_id}")
async def lookup_order_remake(order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderRemakeService(db).lookup(order_id, client_operation_id, actor))
    except CreationError as error:
        raise _http_error(error) from None


@router.post("/remake/{order_id}/{client_operation_id}/resume")
async def resume_order_remake(order_id: str, client_operation_id: str, request: Request,
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _remake_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderRemakeService(db).resume(order_id, client_operation_id, actor))
    except CreationError as error:
        raise _http_error(error) from None


def _response(outcome):
    headers = {"Cache-Control": "no-store"}
    if outcome.result.state == "pending":
        headers["Retry-After"] = str(outcome.result.retry_after_seconds)
    return JSONResponse(outcome.result.model_dump(mode="json"), status_code=outcome.status_code, headers=headers)


def _http_error(exc):
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message},
                         headers={"Cache-Control": "no-store"})


@router.get("/preparation/capabilities")
async def order_preparation_capabilities(
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderPreparationService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except PreparationError as exc:
        raise _http_error(exc) from None


@router.put("/preparing/{order_id}")
async def start_recoverable_preparation(
    order_id: str, command: PreparingOperationCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderPreparationService(db, "preparing").submit(order_id, command, actor))
    except PreparationError as exc:
        raise _http_error(exc) from None


@router.put("/ready/{order_id}")
async def complete_recoverable_preparation(
    order_id: str, command: ReadyOperationCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderPreparationService(db, "ready").submit(order_id, command, actor))
    except PreparationError as exc:
        raise _http_error(exc) from None


async def _lookup_preparation(operation_type, order_id, client_operation_id, actor, expected_actor_id):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderPreparationService(db, operation_type).lookup(order_id, client_operation_id, actor))
    except PreparationError as exc:
        raise _http_error(exc) from None


async def _resume_preparation(operation_type, order_id, client_operation_id, request, actor, expected_actor_id):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderPreparationService(db, operation_type).resume(order_id, client_operation_id, actor))
    except PreparationError as exc:
        raise _http_error(exc) from None


@router.get("/preparing/{order_id}/{client_operation_id}")
async def lookup_order_preparation(
    order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    return await _lookup_preparation("preparing", order_id, client_operation_id, actor, expected_actor_id)


@router.get("/ready/{order_id}/{client_operation_id}")
async def lookup_order_ready(
    order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    return await _lookup_preparation("ready", order_id, client_operation_id, actor, expected_actor_id)


@router.post("/preparing/{order_id}/{client_operation_id}/resume")
async def resume_order_preparation(
    order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    return await _resume_preparation("preparing", order_id, client_operation_id, request, actor, expected_actor_id)


@router.post("/ready/{order_id}/{client_operation_id}/resume")
async def resume_order_ready(
    order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    return await _resume_preparation("ready", order_id, client_operation_id, request, actor, expected_actor_id)


@router.post("/create")
async def create_recoverable_order(
    command: CreateOrderCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return _response(await OrderCreationService(db).create(command, actor))
    except CreationError as exc:
        raise _http_error(exc) from exc


@router.get("/capabilities")
async def order_creation_capabilities(
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderCreationService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except CreationError as exc:
        raise _http_error(exc) from exc


@router.post("/create/{client_operation_id}/resume")
async def resume_order_creation(
    client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        OperationCommand(client_operation_id=client_operation_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."},
                            headers={"Cache-Control": "no-store"}) from exc
    # Reject the first nonempty chunk without collecting or echoing a body.
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."},
                                headers={"Cache-Control": "no-store"})
    try:
        return _response(await OrderCreationService(db).resume(client_operation_id, actor))
    except CreationError as exc:
        raise _http_error(exc) from exc


@router.get("/create/{client_operation_id}")
async def lookup_order_creation(
    client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        OperationCommand(client_operation_id=client_operation_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."},
                            headers={"Cache-Control": "no-store"}) from exc
    try:
        return _response(await OrderCreationService(db).lookup(client_operation_id, actor))
    except CreationError as exc:
        raise _http_error(exc) from exc


def _edit_path(order_id, client_operation_id=None):
    if (not 1 <= len(order_id) <= 120 or order_id != order_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in order_id)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_ORDER_ID", "message": "Identitate invalida."})
    if client_operation_id is not None:
        try:
            OperationCommand(client_operation_id=client_operation_id)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."}) from exc


@router.get("/edit/capabilities")
async def order_editing_capabilities(
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderEditingService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except EditingError as exc:
        raise _http_error(exc) from exc


@router.post("/edit/{order_id}")
async def edit_recoverable_order(
    order_id: str, command: EditOrderCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderEditingService(db).edit(order_id, command, actor))
    except EditingError as exc:
        raise _http_error(exc) from exc


@router.get("/edit/{order_id}/{client_operation_id}")
async def lookup_order_editing(
    order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderEditingService(db).lookup(order_id, client_operation_id, actor))
    except EditingError as exc:
        raise _http_error(exc) from exc


@router.post("/edit/{order_id}/{client_operation_id}/resume")
async def resume_order_editing(
    order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    try:
        return _response(await OrderEditingService(db).resume(order_id, client_operation_id, actor))
    except EditingError as exc:
        raise _http_error(exc) from exc


def _assign_actor_context(actor, expected_actor_id):
    if expected_actor_id is None:
        return
    if (not isinstance(expected_actor_id, str) or not 1 <= len(expected_actor_id) <= 120
        or expected_actor_id != expected_actor_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in expected_actor_id)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_EXPECTED_ACTOR_ID", "message": "Identitate invalida."})
    if expected_actor_id != (actor.get("user_id") or actor.get("id")):
        raise HTTPException(status_code=403, detail={"code": "AUTH_CONTEXT_CHANGED", "message": "Sesiunea s-a schimbat."})


@router.get("/assign/capabilities")
async def order_assignment_capabilities(
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderAssignmentService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except AssignmentError as exc:
        raise _http_error(exc) from exc


@router.post("/assign/{order_id}")
async def assign_recoverable_order(
    order_id: str, command: AssignOrderCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderAssignmentService(db).assign(order_id, command, actor))
    except AssignmentError as exc:
        raise _http_error(exc) from exc


@router.get("/assign/{order_id}/{client_operation_id}")
async def lookup_order_assignment(
    order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderAssignmentService(db).lookup(order_id, client_operation_id, actor))
    except AssignmentError as exc:
        raise _http_error(exc) from exc


@router.post("/assign/{order_id}/{client_operation_id}/resume")
async def resume_order_assignment(
    order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderAssignmentService(db).resume(order_id, client_operation_id, actor))
    except AssignmentError as exc:
        raise _http_error(exc) from exc


@router.get("/status/capabilities")
async def order_status_capabilities(
    actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OrderStatusService(db).capabilities(actor), headers={"Cache-Control": "no-store"})
    except StatusError as exc:
        raise _http_error(exc) from exc


@router.post("/status/{order_id}")
async def change_recoverable_order_status(
    order_id: str, command: StatusOrderCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id)
    try:
        return _response(await OrderStatusService(db).status(order_id, command, actor))
    except StatusError as exc:
        raise _http_error(exc) from exc


@router.get("/status/{order_id}/{client_operation_id}")
async def lookup_order_status(
    order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        return _response(await OrderStatusService(db).lookup(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from exc


@router.post("/status/{order_id}/{client_operation_id}/resume")
async def resume_order_status(
    order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _assign_actor_context(actor, expected_actor_id)
    _edit_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _response(await OrderStatusService(db).resume(order_id, client_operation_id, actor))
    except StatusError as exc:
        raise _http_error(exc) from exc


def _incident_path(order_id, operation_id=None):
    _edit_path(order_id)
    if operation_id is not None:
        try:
            OperationalCommand(client_operation_id=operation_id)
        except ValidationError:
            raise HTTPException(status_code=422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."}) from None

def _reporting_response(outcome):
    headers = {"Cache-Control": "no-store"}
    if outcome.result["state"] == "pending":
        headers["Retry-After"] = str(outcome.result["retry_after_seconds"])
    return JSONResponse(outcome.result, status_code=outcome.status_code, headers=headers)

@router.get("/incident/capabilities")
async def incident_capabilities(actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OperationalReportingService(db, "incident").capabilities(actor), headers={"Cache-Control": "no-store"})
    except ReportingError as error:
        raise _http_error(error) from None

@router.post("/incident/{order_id}")
async def report_order_incident(order_id: str, command: IncidentCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id); _incident_path(order_id)
    try:
        return _reporting_response(await OperationalReportingService(db, "incident").submit(order_id, command, actor))
    except ReportingError as error:
        raise _http_error(error) from None

@router.get("/incident/{order_id}/{client_operation_id}")
async def lookup_order_incident(order_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id); _incident_path(order_id, client_operation_id)
    try:
        return _reporting_response(await OperationalReportingService(db, "incident").lookup(order_id, client_operation_id, actor))
    except ReportingError as error:
        raise _http_error(error) from None

@router.post("/incident/{order_id}/{client_operation_id}/resume")
async def resume_order_incident(order_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id); _incident_path(order_id, client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return _reporting_response(await OperationalReportingService(db, "incident").resume(order_id, client_operation_id, actor))
    except ReportingError as error:
        raise _http_error(error) from None
