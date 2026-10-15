"""Custody proof validation: pure binding first, bounded exact ledger verification second."""
from datetime import datetime, timedelta
import uuid
from pydantic import ValidationError
from models.custody_activity import CustodyActivity, CustodyBinding, activity_digest, digest


class CustodyError(Exception):
    code = "CUSTODY_INVALID"


def present(order, projected=False):
    actual = "custody_activity" in order or "custody_contract_version" in order
    return order.get("_read_has_custody", actual) if projected else actual


def finance_binding(order):
    return digest({k: order.get(k) for k in ("financial", "financial_contract_version", "creation_operation_ref",
        "financial_activity", "financial_activity_contract_version", "payment_type", "subtotal_amount", "delivery_fee", "total_amount")})


def inspect_custody(order, *, projected=False):
    if not present(order, projected):
        return None
    try:
        if type(order.get("custody_contract_version")) is not int or order["custody_contract_version"] != 1:
            raise ValueError()
        activity = CustodyActivity.model_validate(order["custody_activity"])
        binding = activity.binding
        if binding.order_id != order.get("id"):
            raise ValueError()
        if any(getattr(binding, k) != order.get(k) for k in ("restaurant_id", "driver_id", "assigned_at", "accepted_at", "picked_up_at")):
            raise ValueError()
        if binding.products_digest != digest(order.get("_read_custody_items") if projected else order.get("items")) or binding.finance_digest != finance_binding(order):
            raise ValueError()
        status = order.get("status")
        latest = activity.resolved_at or activity.decided_at or activity.reviewed_at or activity.wait_started_at
        if status == "CANCELLED":
            if (activity.status not in {"returned", "kept"} or order.get("cancelled_at") != activity.resolved_at
                or order.get("cancellation_reason") != "custody_" + activity.status or not order.get("cancelled_by")
                or order.get("delivered_at") is not None):
                raise ValueError()
        elif status == "DELIVERED":
            delivered = datetime.fromisoformat(order["delivered_at"])
            if (activity.status not in {"waiting", "reviewed"} or delivered.tzinfo is None
                or delivered < datetime.fromisoformat(latest) or any(order.get(k) is not None for k in ("cancelled_at", "cancelled_by", "cancellation_reason"))):
                raise ValueError()
        elif status != "PICKED_UP" or activity.status in {"returned", "kept"} or any(order.get(k) is not None for k in ("delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason")):
            raise ValueError()
        return activity
    except (ValidationError, KeyError, TypeError, ValueError, OverflowError):
        raise CustodyError() from None


def evolve(previous, command, binding, event_id, now):
    if previous is None:
        value = {"contract_version": 1, "status": "waiting", "driver_id": binding["driver_id"],
            "incident_id": command.incident_id, "reason": command.reason, "arrival_evidence": "declared",
            "wait_event_id": event_id, "wait_started_at": now,
            "wait_eligible_at": (datetime.fromisoformat(now) + timedelta(seconds=600)).isoformat(),
            "review_id": None, "reviewed_at": None, "customer_contact_attempted": None,
            "restaurant_contacted": None, "coordination_confirmed": None,
            "decision_id": None, "decision": None, "decided_at": None,
            "resolution_id": None, "resolved_at": None, "pricing_status": "pending",
            "binding": binding, "event_ids": []}
    else:
        value = previous.model_dump(mode="json")
        if command.event_type == "delivery_failure_reviewed":
            value.update(status="reviewed", review_id=event_id, reviewed_at=now,
                customer_contact_attempted=True, restaurant_contacted=True, coordination_confirmed=True)
        elif command.event_type == "products_disposition_decided":
            value.update(status="return_requested" if command.decision == "return" else "keep_authorized",
                decision_id=event_id, decision=command.decision, decided_at=now)
        else:
            value.update(status="returned" if command.event_type == "products_return_received" else "kept",
                resolution_id=event_id, resolved_at=now)
    value["event_ids"].append(event_id)
    value["activity_digest"] = activity_digest(value)
    return CustodyActivity.model_validate(value)


def validate_rows(order, activity, rows, incident):
    from models.order_custody import CustodyCommand, ROLES
    try:
        if len(rows) != len(activity.event_ids) or len({r["_id"] for r in rows}) != len(rows):
            raise ValueError()
        by_id = {r["_id"]: r for r in rows}
        previous, last_version = None, -1
        for index, event_id in enumerate(activity.event_ids):
            row = by_id[event_id]
            command = CustodyCommand.model_validate(row["command"])
            expected_type = ("delivery_wait_started", "delivery_failure_reviewed", "products_disposition_decided",
                "products_return_received" if activity.decision == "return" else "products_keep_acknowledged")[index]
            operation_ref = "custody:" + digest([row["actor_id"], "custody", command.client_operation_id])
            if (set(row) != {"_id", "id", "contract_version", "event_type", "order_id", "restaurant_id", "driver_id", "actor_id", "actor_role",
                "operation_ref", "command", "binding", "created_at", "event_digest", "from_order_version", "to_order_version"}
                or row["id"] != event_id or type(row["contract_version"]) is not int or row["contract_version"] != 1
                or row["event_type"] != expected_type or command.event_type != expected_type
                or command.incident_id != activity.incident_id or row["actor_role"] != ROLES[expected_type]
                or row["order_id"] != order["id"] or row["restaurant_id"] != order["restaurant_id"]
                or row["driver_id"] != order["driver_id"] or row["binding"] != activity.binding.model_dump(mode="json")
                or row["operation_ref"] != operation_ref or str(uuid.uuid5(uuid.NAMESPACE_URL, operation_ref + ":event")) != event_id
                or row["event_digest"] != digest({k: v for k, v in row.items() if k not in {"_id", "event_digest"}})
                or not isinstance(row["actor_id"], str) or not 1 <= len(row["actor_id"]) <= 120
                or row["actor_role"] == "driver" and row["actor_id"] != activity.binding.driver_user_id
                or type(row["from_order_version"]) is not int or row["from_order_version"] != command.expected_order_version
                or row["from_order_version"] <= last_version or row["to_order_version"] != row["from_order_version"] + 1
                or index > 0 and command.predecessor_id != activity.event_ids[index - 1]):
                raise ValueError()
            previous = evolve(previous, command, row["binding"], event_id, row["created_at"])
            last_version = row["from_order_version"]
        if previous != activity or order.get("order_version", -1) < last_version + 1:
            raise ValueError()
        validate_incident(incident, order, activity.binding.driver_user_id)
        if digest({k: v for k, v in incident.items() if k != "_id"}) != activity.binding.incident_digest:
            raise ValueError()
        if datetime.fromisoformat(incident["reported_at"]) > datetime.fromisoformat(activity.wait_started_at):
            raise ValueError()
        if order.get("status") == "CANCELLED" and order.get("cancelled_by") != by_id[activity.resolution_id]["actor_id"]:
            raise ValueError()
    except (ValidationError, KeyError, TypeError, ValueError, OverflowError, CustodyError):
        raise CustodyError() from None


def validate_incident(incident, order, driver_user_id):
    try:
        reported = datetime.fromisoformat(incident["reported_at"])
        if (incident["_id"] != incident["id"] or incident["id"] != str(uuid.UUID(incident["id"])) or incident["incident_type"] != "delivery_blocked"
            or incident["order_id"] != order["id"] or incident["restaurant_id"] != order["restaurant_id"]
            or incident["driver_id_at_report"] != order["driver_id"] or incident["status_at_report"] != "PICKED_UP"
            or incident["performed_by_role"] != "driver" or incident["performed_by"] != driver_user_id
            or reported.tzinfo is None or reported < datetime.fromisoformat(order["picked_up_at"])):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise CustodyError() from None


async def validate_custody_ledger(database, order, activity, session=None):
    if activity is None:
        return
    rows = await database.get_collection("order_custody_events").find({"_id": {"$in": activity.event_ids}}, session=session).limit(5).to_list(5)
    incident = await database.order_incidents.find_one({"_id": activity.incident_id}, session=session)
    validate_rows(order, activity, rows, incident)


async def read_custody_failures(database, documents, *, projected=False):
    if len(documents) > 1000:
        raise CustodyError()
    invalid, pending, ids, incidents = set(), [], set(), set()
    for index, order in enumerate(documents):
        try:
            activity = inspect_custody(order, projected=projected)
            if activity:
                pending.append((index, order, activity)); ids.update(activity.event_ids); incidents.add(activity.incident_id)
        except CustodyError:
            invalid.add(index)
    if not pending:
        return invalid
    async def bounded(collection, keys, size):
        values = await collection.aggregate([{"$match": {"_id": {"$in": sorted(keys)}}}, {"$limit": len(keys) + 1},
            {"$project": {"_id": 1, "row": {"$cond": [{"$lte": [{"$bsonSize": "$$ROOT"}, size]}, "$$ROOT", None]}}}], maxTimeMS=3000).to_list(len(keys) + 1)
        return {v["_id"]: v.get("row") for v in values}
    rows = await bounded(database.order_custody_events, ids, 16384)
    reports = await bounded(database.order_incidents, incidents, 8192)
    for index, order, activity in pending:
        try:
            validate_rows(order, activity, [rows[k] for k in activity.event_ids if rows.get(k) is not None], reports.get(activity.incident_id))
        except CustodyError:
            invalid.add(index)
    return invalid


def unavailable_custody_read(value):
    value.update(custody_activity=None, custody_contract_version=None, read_custody_invalid=True, read_actions_unavailable=True)
    # A terminal L4A debt is readable only with the transitive custody proof.
    if value.get("status") == "CANCELLED" and value.get("picked_up_at") is not None and value.get("financial_activity") is not None:
        value.update(financial_activity=None, financial_activity_contract_version=None, read_financial_activity_invalid=True)
    return value


def public_custody_read(order):
    if not present(order):
        return order
    value = dict(order)
    try:
        value.update(custody_activity=inspect_custody(order).public(), custody_contract_version=1)
    except CustodyError:
        unavailable_custody_read(value)
    return value
