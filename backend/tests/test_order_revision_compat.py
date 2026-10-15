"""Independent S2-COMPAT evidence; synthetic persistence, never application DB.

Run with the isolated pytest bootstrap documented in QA_NOTES.md. The matcher
models the relevant BSON distinctions and fails closed on unknown operators.
This is not proof of real Mongo atomicity or a release approval.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path

from bson.int64 import Int64
from fastapi import HTTPException
import pytest


MAX_VERSION = 2**63 - 1
MISSING = object()
INVALID_VERSIONS = [None, False, True, "0", "1", 0.0, 1.0, -1,
                    MAX_VERSION + 1, [], [0], {}, float("nan"), float("inf")]


@pytest.fixture
def revision():
    module = importlib.import_module("utils.order_revision")
    assert Path(module.__file__).resolve() == Path(__file__).resolve().parents[1] / "utils" / "order_revision.py"
    for name in ("revision_filter", "revision_update", "ensure_legacy_order"):
        assert callable(getattr(module, name, None)), f"Missing contract export {name}"
    return module


def bson_type(value):
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Int64):
        return "long"
    if type(value) is int:
        return "int" if -(2**31) <= value < 2**31 else "long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise AssertionError(f"Unsupported synthetic BSON value {value!r}")


def bson_equal(left, right):
    numeric = {"int", "long", "double"}
    a, b = bson_type(left), bson_type(right)
    return (a == b or {a, b} <= numeric) and left == right


def expression(document, node):
    if isinstance(node, str) and node.startswith("$"):
        return document.get(node[1:], MISSING)
    if isinstance(node, list):
        return [expression(document, part) for part in node]
    if not isinstance(node, dict):
        return node
    assert len(node) == 1, f"Unsupported expression {node!r}"
    op, args = next(iter(node.items()))
    if op == "$literal":
        return args
    if op == "$type":
        return bson_type(expression(document, args))
    values = expression(document, args)
    if op == "$eq":
        return bson_equal(*values)
    if op == "$ne":
        return not bson_equal(*values)
    if op == "$in":
        return any(bson_equal(values[0], item) for item in values[1])
    if op == "$and":
        return all(values)
    if op == "$or":
        return any(values)
    if op == "$not":
        return not values[0]
    raise AssertionError(f"Unsupported expression operator {op}")


def query_equal(actual, wanted):
    # Mongo field equality can match an array element and null matches absence.
    if actual is MISSING:
        return wanted is None
    return bson_equal(actual, wanted) or (
        isinstance(actual, list) and any(bson_equal(item, wanted) for item in actual)
    )


def field_matches(actual, condition):
    if not isinstance(condition, dict):
        return query_equal(actual, condition)
    results = []
    for op, wanted in condition.items():
        if op == "$exists":
            results.append((actual is not MISSING) == wanted)
        elif op in {"$eq", "$ne"}:
            equal = query_equal(actual, wanted)
            results.append(equal if op == "$eq" else not equal)
        elif op == "$type":
            aliases = {16: "int", 18: "long", 1: "double", 4: "array", 8: "bool"}
            types = wanted if isinstance(wanted, list) else [wanted]
            types = [aliases.get(item, item) for item in types]
            candidates = [actual] + (actual if isinstance(actual, list) else [])
            results.append(any(bson_type(item) in types for item in candidates))
        elif op == "$not":
            results.append(not field_matches(actual, wanted))
        elif op in {"$in", "$nin"}:
            found = any(query_equal(actual, item) for item in wanted)
            results.append(found if op == "$in" else not found)
        else:
            raise AssertionError(f"Unsupported field operator {op}")
    return all(results)


def matches(document, query):
    results = []
    for key, wanted in query.items():
        if key in {"$and", "$or", "$nor"}:
            assert isinstance(wanted, list) and wanted
            branches = [matches(document, branch) for branch in wanted]
            results.append(all(branches) if key == "$and" else
                           any(branches) if key == "$or" else not any(branches))
        elif key == "$expr":
            results.append(bool(expression(document, wanted)))
        else:
            assert not key.startswith("$"), f"Unsupported query operator {key}"
            results.append(field_matches(document.get(key, MISSING), wanted))
    return all(results)


def apply_update(document, update):
    assert set(update) <= {"$set", "$inc", "$push", "$unset"}
    document.update(deepcopy(update.get("$set", {})))
    for key, value in update.get("$inc", {}).items():
        document[key] = document.get(key, 0) + value
    for key, value in update.get("$push", {}).items():
        document.setdefault(key, []).append(deepcopy(value))
    for key in update.get("$unset", {}):
        document.pop(key, None)


def test_matcher_distinguishes_bson_numeric_boolean_missing_and_array():
    assert not matches({"order_version": False}, {"order_version": 0})
    assert matches({"order_version": 0.0}, {"order_version": 0})
    assert matches({"order_version": [0]}, {"order_version": {"$eq": 0, "$type": ["int", "long"]}})
    assert matches({}, {"order_version": None})
    assert not matches({"order_version": None}, {"order_version": {"$exists": False}})
    with pytest.raises(AssertionError, match="Unsupported"):
        matches({"id": "different"}, {"id": "wanted", "$unknown": True})


def test_legacy_filter_is_explicit_absence_and_never_backfills(revision):
    order = {"id": "legacy", "notes": "unchanged"}
    before = deepcopy(order)
    query = revision.revision_filter(order)
    assert query == {"order_version": {"$exists": False}}
    assert matches(order, query)
    assert not matches({**order, "order_version": None}, query)
    assert not matches({**order, "order_version": 0}, query)
    update = revision.revision_update(order, {"$set": {"notes": "new"}})
    assert "order_version" not in update.get("$inc", {})
    assert order == before
    apply_update(order, update)
    assert "order_version" not in order


@pytest.mark.parametrize("value", [0, 1, 2**31 - 1, 2**31, MAX_VERSION, Int64(0), Int64(MAX_VERSION)])
def test_valid_scalar_revision_filter_matches_only_equal_integer(revision, value):
    order = {"id": "versioned", "order_version": value}
    before = deepcopy(order)
    query = revision.revision_filter(order)
    assert order == before
    assert matches(order, query)
    assert matches({"order_version": int(value)}, query)
    assert matches({"order_version": Int64(value)}, query)
    for invalid in INVALID_VERSIONS + [[int(value)], float(value), str(value), int(value) + 1]:
        assert not matches({"order_version": invalid}, query), f"CAS accepts {invalid!r}: {query!r}"
    assert not matches({}, query)


@pytest.mark.parametrize("value", INVALID_VERSIONS)
@pytest.mark.parametrize("helper", ["revision_filter", "revision_update"])
def test_invalid_revision_conflicts_without_mutating_inputs(revision, value, helper):
    order = {"order_version": value}
    update = {"$set": {"notes": "keep"}, "$inc": {"attempts": 2}}
    with pytest.raises(HTTPException) as caught:
        if helper == "revision_filter":
            revision.revision_filter(order)
        else:
            revision.revision_update(order, update)
    assert caught.value.status_code == 409
    assert order["order_version"] is value
    assert update == {"$set": {"notes": "keep"}, "$inc": {"attempts": 2}}


@pytest.mark.parametrize("value", [MISSING, 0, 7, Int64(2**31), MAX_VERSION - 1])
def test_update_is_deeply_detached_preserves_payload_and_increments_once(revision, value):
    order = {} if value is MISSING else {"order_version": value}
    update = {"$set": {"notes": "new", "nested": {"items": [1]}},
              "$inc": {"attempts": 2}, "$push": {"audit_trail": {"changes": {"status": "READY"}}}}
    before_order, before_update = deepcopy(order), deepcopy(update)
    result = revision.revision_update(order, update)
    assert result is not update
    assert result["$set"] == update["$set"]
    assert result["$push"] == update["$push"]
    assert result["$inc"].get("attempts") == 2
    if value is MISSING:
        assert "order_version" not in result["$inc"]
    else:
        assert type(result["$inc"]["order_version"]) is int
        assert result["$inc"]["order_version"] == 1
    result["$set"]["nested"]["items"].append(2)
    result["$push"]["audit_trail"]["changes"]["status"] = "CANCELLED"
    result["$inc"]["attempts"] = 99
    assert update == before_update
    assert order == before_order


def test_maximum_revision_can_be_filtered_but_cannot_be_incremented(revision):
    order = {"order_version": MAX_VERSION}
    assert matches(order, revision.revision_filter(order))
    with pytest.raises(HTTPException) as caught:
        revision.revision_update(order, {"$set": {"notes": "overflow"}})
    assert caught.value.status_code == 409
    assert order["order_version"] == MAX_VERSION


@pytest.mark.parametrize("value", [0, 5, MAX_VERSION - 1])
def test_stale_same_state_writes_allow_only_one_commit(revision, value):
    document = {"id": "same-state", "status": "ASSIGNED", "order_version": value}
    first, second = deepcopy(document), deepcopy(document)
    query_a, query_b = revision.revision_filter(first), revision.revision_filter(second)
    update_a = revision.revision_update(first, {"$set": {"notes": "winner"}})
    update_b = revision.revision_update(second, {"$set": {"notes": "stale"}})
    assert matches(document, query_a)
    apply_update(document, update_a)
    assert not matches(document, query_b)
    assert document["status"] == "ASSIGNED"
    assert document["order_version"] == value + 1
    assert document["notes"] == "winner"
    assert update_b["$inc"]["order_version"] == 1


@pytest.mark.parametrize("value", [0, 1, MAX_VERSION, Int64(0)] + INVALID_VERSIONS)
def test_unsupported_multi_document_writer_refuses_any_revision_presence(revision, value):
    order = {"id": "unsupported", "order_version": value}
    with pytest.raises(HTTPException) as caught:
        revision.ensure_legacy_order(order)
    assert caught.value.status_code == 409
    assert order["order_version"] is value


def test_unsupported_writer_allows_legacy_without_mutation(revision):
    order = {"id": "legacy", "status": "NEW"}
    revision.ensure_legacy_order(order)
    assert order == {"id": "legacy", "status": "NEW"}
