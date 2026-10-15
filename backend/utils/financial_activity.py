"""Validate quote/assignment/custody binding independently of deployment gates."""
from pydantic import ValidationError
from hashlib import sha256
import json
import uuid
from models.financial_activity import FinancialActivity, activity_digest
from utils.custody_activity import inspect_custody, validate_custody_ledger, read_custody_failures, CustodyError
from utils.order_finance import FinanceError, order_financial_snapshot


def inspect_activity(order, *, projected=False):
    present = "financial_activity" in order or "financial_activity_contract_version" in order
    if projected:
        present = order.get("_read_has_financial_activity", present)
    if not present:
        return None
    try:
        if type(order.get("financial_activity_contract_version")) is not int or order["financial_activity_contract_version"] != 1:
            raise ValueError()
        activity = FinancialActivity.model_validate(order["financial_activity"])
        quote = order_financial_snapshot(order)
        if (quote is None or order.get("payment_type") != "CASH" or quote.advance_required_bani <= 0
            or activity.declared_unpaid_bani != quote.advance_required_bani
            or activity.financial_snapshot_digest != quote.snapshot_digest
            or activity.order_id != order.get("id") or activity.restaurant_id != order.get("restaurant_id")
            or activity.driver_id != order.get("driver_id") or activity.assigned_at != order.get("assigned_at")
            or activity.accepted_at != order.get("accepted_at")):
            raise ValueError()
        status = order.get("status")
        if activity.status == "outstanding":
            if (status not in {"PICKED_UP", "DELIVERED"} and not (status == "CANCELLED" and inspect_custody(order, projected=projected) is not None)
                or activity.picked_up_at != order.get("picked_up_at")):
                raise ValueError()
        elif status not in {"ACCEPTED", "CANCELLED"} or order.get("picked_up_at") is not None:
            raise ValueError()
        return activity
    except (ValidationError, KeyError, TypeError, ValueError, FinanceError, CustodyError):
        raise FinanceError("FINANCIAL_ACTIVITY_INVALID") from None


def activity_after_pickup(activity, now, event_id, actor_id):
    value = activity.model_dump(mode="json")
    value.update(status="outstanding", picked_up_at=now, outstanding_bani=activity.declared_unpaid_bani,
        repayment_due_policy="next_pickup_else_shift_end", pickup_event_id=event_id, pickup_actor_id=actor_id)
    value["activity_digest"] = activity_digest(value)
    return FinancialActivity.model_validate(value).model_dump(mode="json")


async def validate_activity_ledger(database, order, activity, session=None):
    """At most three exact event IDs; projection alone never grants custody."""
    if activity is None:
        return
    ids = [activity.declaration_id]
    if activity.approval_id is not None:
        ids.append(activity.approval_id)
    if activity.pickup_event_id is not None:
        ids.append(activity.pickup_event_id)
    rows = await database.get_collection("order_financial_events").find({"_id": {"$in": ids}}, session=session).limit(4).to_list(4)
    _validate_activity_rows(order, activity, ids, rows)
    if order.get("status") == "CANCELLED" and activity.status == "outstanding":
        try:
            await validate_custody_ledger(database, order, inspect_custody(order), session)
        except CustodyError:
            raise FinanceError("FINANCIAL_ACTIVITY_INVALID") from None


def _validate_activity_rows(order, activity, ids, rows):
    try:
        if len(set(ids)) != len(ids) or len(rows) != len(ids):
            raise ValueError()
        by_id = {row["_id"]: row for row in rows}
        for index, event_id in enumerate(ids):
            row = by_id[event_id]
            event_type = ("advance_not_paid_declared", "advance_shortfall_acknowledged", "unpaid_pickup_recorded")[index]
            suffix = ":financial-pickup" if index == 2 else ":event"
            role = "driver" if index == 0 else "restaurant" if index == 1 else None
            expected_at = (activity.declared_at, activity.approved_at, activity.picked_up_at)[index]
            digest = sha256(json.dumps({k: v for k, v in row.items() if k not in {"_id", "event_digest"}},
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            if (row["id"] != event_id or type(row["contract_version"]) is not int or row["contract_version"] != 1
                or row["event_type"] != event_type or row["order_id"] != order["id"]
                or row["restaurant_id"] != order["restaurant_id"] or row["driver_id"] != activity.driver_id
                or type(row["amount_bani"]) is not int or row["amount_bani"] != activity.declared_unpaid_bani
                or row["declaration_id"] != activity.declaration_id
                or row["financial_snapshot_digest"] != activity.financial_snapshot_digest
                or row["assigned_at"] != activity.assigned_at or row["accepted_at"] != activity.accepted_at
                or row["created_at"] != expected_at or row["event_digest"] != digest
                or str(uuid.uuid5(uuid.NAMESPACE_URL, row["operation_ref"] + suffix)) != event_id
                or role is not None and row["actor_role"] != role
                or row["actor_id"] != (activity.declaration_actor_id, activity.approval_actor_id, activity.pickup_actor_id)[index]
                or index == 2 and row["actor_role"] not in {"admin", "driver"}
                or not isinstance(row["actor_id"], str) or not 1 <= len(row["actor_id"]) <= 120):
                raise ValueError()
            if index == 2 and (row["approval_id"] != activity.approval_id or row["repayment_due_policy"] != "next_pickup_else_shift_end"):
                raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise FinanceError("FINANCIAL_ACTIVITY_INVALID") from None


async def read_activity_failures(database, documents, *, projected=False):
    """One bounded exact-ID ledger query per page; no private fields reach the caller."""
    if len(documents) > 1000:
        raise FinanceError("FINANCIAL_ACTIVITY_INVALID")
    invalid, pending = set(), []
    cancelled = [(i, v) for i, v in enumerate(documents) if v.get("status") == "CANCELLED" and v.get("picked_up_at") is not None]
    if cancelled:
        for i in await read_custody_failures(database, [v for _, v in cancelled], projected=projected):
            invalid.add(cancelled[i][0])
    all_ids, orders, restaurants = set(), set(), set()
    for index, order in enumerate(documents):
        try:
            activity = inspect_activity(order, projected=projected)
            if activity is None:
                continue
            ids = [v for v in (activity.declaration_id, activity.approval_id, activity.pickup_event_id) if v is not None]
            pending.append((index, order, activity, ids))
            all_ids.update(ids)
            orders.add(order["id"])
            restaurants.add(order["restaurant_id"])
        except FinanceError:
            invalid.add(index)
    if not pending:
        return invalid
    pipeline = [{"$match": {"_id": {"$in": sorted(all_ids)}, "order_id": {"$in": sorted(orders)},
        "restaurant_id": {"$in": sorted(restaurants)}}}, {"$limit": len(all_ids) + 1},
        {"$project": {"_id": 1, "row": {"$cond": [{"$lte": [{"$bsonSize": "$$ROOT"}, 8192]}, "$$ROOT", None]}}}]
    values = await database.order_financial_events.aggregate(pipeline, maxTimeMS=3000).to_list(len(all_ids) + 1)
    by_id = {value["_id"]: value.get("row") for value in values}
    for index, order, activity, ids in pending:
        try:
            _validate_activity_rows(order, activity, ids, [by_id[event_id] for event_id in ids if by_id.get(event_id) is not None])
        except FinanceError:
            invalid.add(index)
    return invalid


def unavailable_activity_read(value):
    value.update(financial_activity=None, financial_activity_contract_version=None,
        read_financial_activity_invalid=True, read_actions_unavailable=True)
    return value


def public_activity_read(order):
    """Raw compatibility reads must never return private projection bindings."""
    if not ("financial_activity" in order or "financial_activity_contract_version" in order):
        return order
    value = dict(order)
    try:
        value["financial_activity"] = inspect_activity(order).public()
        value["financial_activity_contract_version"] = 1
    except FinanceError:
        value["financial_activity"] = None
        value["financial_activity_contract_version"] = None
        value["read_financial_activity_invalid"] = True
        value["read_actions_unavailable"] = True
    return value
