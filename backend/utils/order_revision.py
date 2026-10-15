"""Business revision compatibility; never backfill a legacy order implicitly."""

from copy import deepcopy
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import threading

from bson.int64 import Int64
from fastapi import HTTPException


MAX_ORDER_VERSION = (1 << 63) - 1
_maintenance_permit = ContextVar("isolated_order_maintenance", default=None)


def _conflict(code, message):
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def revision_filter(order):
    if "order_version" not in order:
        return {"order_version": {"$exists": False}}
    version = order["order_version"]
    if type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION:
        raise _conflict("ORDER_VERSION_INVALID", "Comanda are o versiune invalida; verifica manual.")
    return {"order_version": {
        "$eq": int(version), "$type": ["int", "long"], "$not": {"$type": "array"},
    }}


def revision_update(order, update):
    revision_filter(order)
    result = deepcopy(update)
    if not result or set(result) - {"$set", "$inc", "$push", "$unset"}:
        raise ValueError("Unsupported order revision update")
    for fields in result.values():
        if not isinstance(fields, dict) or any(
            key == "order_version" or key.startswith("order_version.") for key in fields
        ):
            raise ValueError("The business revision is owned by the revision protocol")
    if "order_version" in order:
        if order["order_version"] == MAX_ORDER_VERSION:
            raise _conflict("ORDER_VERSION_EXHAUSTED", "Versiunea comenzii necesita verificare manuala.")
        result.setdefault("$inc", {})["order_version"] = 1
    return result


def ensure_legacy_order(order):
    if "custody_activity" in order or "custody_contract_version" in order:
        raise _conflict("CUSTODY_VERSIONED_OPERATION_REQUIRED", "Custodia necesita protocolul recuperabil.")
    if "financial_activity" in order or "financial_activity_contract_version" in order:
        raise _conflict("FINANCIAL_VERSIONED_OPERATION_REQUIRED",
                        "Evidenta numerarului necesita protocolul recuperabil; operatia legacy este blocata.")
    if "financial" in order or "financial_contract_version" in order:
        raise _conflict("FINANCIAL_VERSIONED_OPERATION_REQUIRED",
                        "Comanda financiara necesita protocolul recuperabil; operatia legacy este blocata.")
    if "order_version" in order:
        raise _conflict(
            "ORDER_VERSIONED_OPERATION_UNSUPPORTED",
            "Aceasta actiune necesita protocolul versionat; comanda nu a fost modificata.",
        )


async def ensure_legacy_order_scope(db, scope=None):
    query = {"$and": [scope or {}, {"$or": [{"order_version": {"$exists": True}},
        {"custody_activity": {"$exists": True}}, {"custody_contract_version": {"$exists": True}}]}]}
    if await db.orders.find_one(query, {"_id": 0, "id": 1}) is not None:
        raise _conflict(
            "ORDER_VERSIONED_OPERATION_UNSUPPORTED",
            "Exista comenzi versionate; operatia de mentenanta nu este permisa.",
        )


def _execution_owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


@contextmanager
def isolated_maintenance_for_fixture(db):
    """Harness-only permit after external fixture ownership/exclusion verification.

    No production router or startup grants this permit. Environment/request flags
    never authorize it; inherited contexts cannot grant it to another task.
    """
    if _maintenance_permit.get() is not None:
        raise RuntimeError("Nested maintenance permits are not supported")
    token = _maintenance_permit.set((db, _execution_owner()))
    try:
        yield
    finally:
        _maintenance_permit.reset(token)


def require_isolated_maintenance(db):
    permit = _maintenance_permit.get()
    if permit is None or permit[0] is not db or permit[1] != _execution_owner():
        raise _conflict(
            "MAINTENANCE_ISOLATION_REQUIRED",
            "Stergerea permanenta/resetarea este blocata pana la mentenanta sigura. "
            "Pentru livratori foloseste dezactivarea contului.",
        )
