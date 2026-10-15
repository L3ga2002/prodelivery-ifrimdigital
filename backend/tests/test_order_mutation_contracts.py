"""Independent additive S2-01 contracts; synthetic HTTP only, no auth or DB.

The runner supplies backend imports (including the staged module override).
This file deliberately does not import the production app or routers.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json as jsonlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import ResponseValidationError
from pydantic import ValidationError

from models.order import OrderCreate, OrderItem, PreparationTime, UpdateOrderStatus
from models.order_mutation import (
    AssignOrderCommand,
    CreateOrderCommand,
    EditOrderCommand,
    MutationIntentConflict,
    MutationResult,
    OrderCorrections,
    PreparationCommand,
    ReadyOrderCommand,
    StatusOrderCommand,
    StrictOrderCreate,
    StrictOrderItem,
    build_mutation_intent,
    compare_mutation_intent,
)


OPERATION_ID = "qa_operation_0001"
MAX_VERSION = 9223372036854775807
COMMAND_MODELS = {
    "create": CreateOrderCommand,
    "edit": EditOrderCommand,
    "assign": AssignOrderCommand,
    "preparing": PreparationCommand,
    "ready": ReadyOrderCommand,
    "status": StatusOrderCommand,
}
VERSIONED_OPERATIONS = tuple(key for key in COMMAND_MODELS if key != "create")
TEXT_BOUNDS = (
    ("restaurant_id", 1, 120),
    ("customer_name", 2, 140),
    ("customer_phone", 7, 24),
    ("customer_address", 5, 300),
    ("source", 1, 12),
    ("notes", 0, 1000),
    ("delivery_zone_id", 0, 120),
    ("delivery_zone_name", 0, 160),
    ("delivery_sector", 0, 80),
    ("problem_description", 0, 1000),
)


def order_payload(**overrides):
    payload = {
        "restaurant_id": "synthetic-restaurant",
        "customer_name": "Synthetic Customer",
        "customer_phone": "0700000000",
        "customer_address": "Synthetic Street 1",
        "items": [{"name": "Synthetic Meal", "quantity": 2, "price": 12.5}],
        "total_amount": 25,
    }
    payload.update(overrides)
    return payload


def command_payload(operation, **overrides):
    payload = {"client_operation_id": OPERATION_ID}
    if operation != "create":
        payload["expected_order_version"] = 0
    payload.update({
        "create": {"order": order_payload()},
        "edit": {"changes": {"notes": "Synthetic correction"}},
        "assign": {"driver_id": "synthetic-driver"},
        "preparing": {"preparation_time": 30},
        "ready": {},
        "status": {"status": "ACCEPTED"},
    }[operation])
    payload.update(overrides)
    return payload


def intent(operation="edit", actor="synthetic-actor", target="synthetic-order", **overrides):
    command = COMMAND_MODELS[operation].model_validate(command_payload(operation, **overrides))
    return build_mutation_intent(actor, operation, target, command)


def result_payload(initial_state, **overrides):
    payload = {"client_operation_id": OPERATION_ID, "state": initial_state}
    if initial_state in ("applied", "replayed"):
        payload.update(order_id="synthetic-order", order_version=0)
    elif initial_state == "pending":
        payload["retry_after_seconds"] = 1
    elif initial_state == "rejected":
        payload["error_code"] = "VERSION_CONFLICT"
    payload.update(overrides)
    return payload


def test_strict_models_extend_legacy_without_changing_money_semantics():
    assert issubclass(StrictOrderItem, OrderItem)
    assert issubclass(StrictOrderCreate, OrderCreate)
    payload = order_payload(subtotal_amount=900, delivery_fee=50, total_amount=1)
    assert StrictOrderCreate.model_validate(payload).model_dump() == OrderCreate.model_validate(payload).model_dump()
    assert StrictOrderCreate.model_validate(payload).total_amount == 1
    # Contracts accept the legacy hint; server-side recalculation is outside S2-01.


@pytest.mark.parametrize("value", [True, False, "2", 2.0, 2.5, None])
def test_item_quantity_is_strict_integer(value):
    with pytest.raises(ValidationError):
        StrictOrderItem(name="Meal", quantity=value, price=1)


@pytest.mark.parametrize("field", ["price", "quantity"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_item_rejects_nonfinite_numbers(field, value):
    payload = {"name": "Meal", "quantity": 1, "price": 1}
    payload[field] = value
    with pytest.raises(ValidationError):
        StrictOrderItem.model_validate(payload)


@pytest.mark.parametrize("value", [True, False, "1.5", None])
def test_item_price_rejects_coercion(value):
    with pytest.raises(ValidationError):
        StrictOrderItem(name="Meal", quantity=1, price=value)


@pytest.mark.parametrize("field,low,high", [("quantity", 1, 100), ("price", 0, 100000)])
def test_item_numeric_bounds(field, low, high):
    for value in (low, high):
        payload = {"name": "Meal", "quantity": 1, "price": 1, field: value}
        StrictOrderItem.model_validate(payload)
    for value in (low - 1, high + 1):
        with pytest.raises(ValidationError):
            StrictOrderItem.model_validate({"name": "Meal", "quantity": 1, "price": 1, field: value})


def test_nested_item_trims_before_bounds_and_preserves_list_limit():
    item = {"name": "  " + "x" * 140 + "  ", "quantity": 1, "price": 0}
    order = StrictOrderCreate.model_validate(order_payload(items=[deepcopy(item) for _ in range(200)]))
    assert len(order.items) == 200
    assert isinstance(order.items[0], StrictOrderItem)
    assert order.items[0].name == "x" * 140
    for bad_name in ("   ", "x" * 141):
        with pytest.raises(ValidationError):
            StrictOrderCreate.model_validate(order_payload(items=[{**item, "name": bad_name}]))
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(items=[item] * 201))


@pytest.mark.parametrize("field,minimum,maximum", TEXT_BOUNDS)
def test_create_text_bounds_apply_after_trimming(field, minimum, maximum):
    for size in (max(minimum, 1), maximum):
        value = "x" * size
        order = StrictOrderCreate.model_validate(order_payload(**{field: " \t" + value + "\n "}))
        assert getattr(order, field) == value
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(**{field: "x" * (maximum + 1)}))
    if minimum:
        with pytest.raises(ValidationError):
            StrictOrderCreate.model_validate(order_payload(**{field: " " + "x" * (minimum - 1) + " "}))


@pytest.mark.parametrize("field", ["restaurant_id", "customer_name", "customer_phone", "customer_address", "notes", "source"])
@pytest.mark.parametrize("value", [True, 123, [], {}])
def test_create_text_does_not_coerce_nonstrings(field, value):
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(**{field: value}))


@pytest.mark.parametrize("field", ["total_amount", "subtotal_amount", "delivery_fee", "customer_latitude", "customer_longitude"])
@pytest.mark.parametrize("value", [True, False, "1.5", float("nan"), float("inf"), -float("inf")])
def test_create_numeric_fields_are_strict_and_finite(field, value):
    payload = order_payload(customer_latitude=0, customer_longitude=0)
    payload[field] = value
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(payload)


@pytest.mark.parametrize("field", ["subtotal_amount", "delivery_fee", "total_amount"])
def test_create_money_keeps_legacy_bounds(field):
    for value in (0, 1000000):
        assert getattr(StrictOrderCreate.model_validate(order_payload(**{field: value})), field) == value
    for value in (-0.01, 1000000.01):
        with pytest.raises(ValidationError):
            StrictOrderCreate.model_validate(order_payload(**{field: value}))


@pytest.mark.parametrize("value", [True, "1", 1.0, -1, 51])
def test_create_zone_level_is_strict_bounded_integer(value):
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(delivery_zone_level=value))


@pytest.mark.parametrize("coordinates", [{}, {"customer_latitude": None, "customer_longitude": None},
                                        {"customer_latitude": -90, "customer_longitude": -180},
                                        {"customer_latitude": 90, "customer_longitude": 180}])
def test_create_coordinate_pair_accepts_absence_clear_and_edges(coordinates):
    StrictOrderCreate.model_validate(order_payload(**coordinates))


@pytest.mark.parametrize("coordinates", [
    {"customer_latitude": 1}, {"customer_longitude": 1},
    {"customer_latitude": None, "customer_longitude": 1},
    {"customer_latitude": 1, "customer_longitude": None},
    {"customer_latitude": 90.1, "customer_longitude": 0},
    {"customer_latitude": 0, "customer_longitude": -180.1},
])
def test_create_rejects_incomplete_or_out_of_range_coordinates(coordinates):
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(**coordinates))


@pytest.mark.parametrize("bad_item", [
    {"name": "Meal", "quantity": True, "price": 1},
    {"name": "Meal", "quantity": 1, "price": "1"},
    {"name": "Meal", "quantity": 1, "price": 1, "status": "DELIVERED"},
    {"name": "Meal", "quantity": 1},
])
def test_create_command_enforces_deep_nested_validation(bad_item):
    with pytest.raises(ValidationError):
        CreateOrderCommand.model_validate(command_payload("create", order=order_payload(items=[bad_item])))


def test_problem_order_consistency_remains_in_force():
    for description in (None, "   "):
        with pytest.raises(ValidationError):
            StrictOrderCreate.model_validate(order_payload(problem_type="missing_product", problem_description=description))
    order = StrictOrderCreate.model_validate(order_payload(problem_type="missing_product", problem_description="  Missing meal  "))
    assert order.problem_description == "Missing meal"


@pytest.mark.parametrize("field", ["actor_id", "authenticated_actor_id", "role", "status", "order_version", "driver_id", "id"])
def test_create_payload_cannot_supply_server_owned_fields(field):
    with pytest.raises(ValidationError):
        CreateOrderCommand.model_validate(command_payload("create", order=order_payload(**{field: "injected"})))


@pytest.mark.parametrize("changes", [{}, {"customer_name": None}, {"customer_phone": None}, {"customer_address": None},
                                    {"customer_name": " x "}, {"customer_phone": " 123456 "}, {"customer_address": " abcd "}])
def test_corrections_require_meaningful_nonnull_required_text(changes):
    with pytest.raises(ValidationError):
        OrderCorrections.model_validate(changes)


@pytest.mark.parametrize("field,minimum,maximum", [entry for entry in TEXT_BOUNDS if entry[0] in {"customer_name", "customer_phone", "customer_address", "notes"}])
def test_correction_text_bounds_apply_after_trimming(field, minimum, maximum):
    value = "x" * maximum
    assert getattr(OrderCorrections.model_validate({field: " " + value + " "}), field) == value
    with pytest.raises(ValidationError):
        OrderCorrections.model_validate({field: "x" * (maximum + 1)})


@pytest.mark.parametrize("field", ["restaurant_id", "driver_id", "status", "items", "total_amount", "delivery_fee", "payment_type", "source", "actor_id", "role", "order_version", "client_operation_id", "unexpected"])
def test_corrections_whitelist_rejects_illegal_fields_even_with_valid_patch(field):
    with pytest.raises(ValidationError):
        EditOrderCommand.model_validate(command_payload("edit", changes={"notes": "ok", field: "injected"}))


@pytest.mark.parametrize("coordinates", [
    {"customer_latitude": None}, {"customer_longitude": None},
    {"customer_latitude": 0}, {"customer_longitude": 0},
    {"customer_latitude": 0, "customer_longitude": None},
    {"customer_latitude": None, "customer_longitude": 0},
    {"customer_latitude": -90.1, "customer_longitude": 0},
    {"customer_latitude": 0, "customer_longitude": 180.1},
])
def test_coordinate_corrections_require_both_explicit_keys(coordinates):
    with pytest.raises(ValidationError):
        OrderCorrections.model_validate({"notes": "ok", **coordinates})


@pytest.mark.parametrize("field", ["customer_latitude", "customer_longitude"])
@pytest.mark.parametrize("value", [True, "0", float("nan"), float("inf"), -float("inf")])
def test_coordinate_corrections_reject_coercion_and_nonfinite(field, value):
    with pytest.raises(ValidationError):
        OrderCorrections.model_validate({"customer_latitude": 0, "customer_longitude": 0, field: value})


def test_corrections_support_explicit_clearing_without_inventing_other_changes():
    patch = OrderCorrections(notes=None)
    assert patch.model_dump(exclude_unset=True) == {"notes": None}
    clear = OrderCorrections(customer_latitude=None, customer_longitude=None)
    assert clear.model_dump(exclude_unset=True) == {"customer_latitude": None, "customer_longitude": None}
    edge = OrderCorrections(customer_latitude=-90, customer_longitude=180)
    assert edge.customer_longitude == 180


@pytest.mark.parametrize("operation", tuple(COMMAND_MODELS))
@pytest.mark.parametrize("operation_id", ["x" * 15, "x" * 129, " " + OPERATION_ID, OPERATION_ID + " ",
                                        OPERATION_ID + "\n", "abcdefghijklmn./", "abcdefghijklmn\u00e9x", True, 123, None])
def test_operation_ids_are_bounded_unpadded_ascii_strings(operation, operation_id):
    with pytest.raises(ValidationError):
        COMMAND_MODELS[operation].model_validate(command_payload(operation, client_operation_id=operation_id))


@pytest.mark.parametrize("operation_id", ["a" * 16, "Z" * 128, "A_z-0123456789_qa"])
def test_operation_id_valid_edges(operation_id):
    assert ReadyOrderCommand.model_validate(command_payload("ready", client_operation_id=operation_id)).client_operation_id == operation_id


@pytest.mark.parametrize("operation", VERSIONED_OPERATIONS)
@pytest.mark.parametrize("value", [True, False, "0", 0.0, 0.5, -1, MAX_VERSION + 1, None])
def test_expected_versions_are_strict_bounded_integers(operation, value):
    with pytest.raises(ValidationError):
        COMMAND_MODELS[operation].model_validate(command_payload(operation, expected_order_version=value))


@pytest.mark.parametrize("operation", VERSIONED_OPERATIONS)
def test_version_required_and_inclusive_boundaries(operation):
    model = COMMAND_MODELS[operation]
    for version in (0, MAX_VERSION):
        assert model.model_validate(command_payload(operation, expected_order_version=version)).expected_order_version == version
    payload = command_payload(operation)
    del payload["expected_order_version"]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("operation", tuple(COMMAND_MODELS))
@pytest.mark.parametrize("field", ["actor_id", "role", "target_order_id", "unexpected"])
def test_command_envelopes_forbid_caller_identity_and_unknown_fields(operation, field):
    with pytest.raises(ValidationError):
        COMMAND_MODELS[operation].model_validate(command_payload(operation, **{field: "injected"}))


@pytest.mark.parametrize("value", [0, 241, True, False, "30", 30.0, None])
def test_preparation_time_strict_bounds(value):
    with pytest.raises(ValidationError):
        PreparationCommand.model_validate(command_payload("preparing", preparation_time=value))


@pytest.mark.parametrize("value", [1, 240])
def test_preparation_time_inclusive_edges(value):
    assert PreparationCommand.model_validate(command_payload("preparing", preparation_time=value)).preparation_time == value


@pytest.mark.parametrize("value", ["", "   ", "x" * 121, True, 123, None])
def test_assignment_requires_bounded_nonblank_string_driver(value):
    with pytest.raises(ValidationError):
        AssignOrderCommand.model_validate(command_payload("assign", driver_id=value))


@pytest.mark.parametrize("status", ["NEW", "PREPARING", "READY", "ASSIGNED", "accepted", "BROKEN", True, None])
def test_status_command_cannot_bypass_dedicated_operations(status):
    with pytest.raises(ValidationError):
        StatusOrderCommand.model_validate(command_payload("status", status=status))


@pytest.mark.parametrize("reason", [None, "", " \t\n ", "x" * 501, True, 123])
def test_cancel_requires_meaningful_bounded_reason(reason):
    with pytest.raises(ValidationError):
        StatusOrderCommand.model_validate(command_payload("status", status="CANCELLED", cancellation_reason=reason))


@pytest.mark.parametrize("status", ["ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"])
def test_valid_status_contracts(status):
    kwargs = {"cancellation_reason": "  " + "x" * 500 + "  "} if status == "CANCELLED" else {}
    command = StatusOrderCommand.model_validate(command_payload("status", status=status, **kwargs))
    assert command.status == status
    if status == "CANCELLED":
        assert command.cancellation_reason == "x" * 500


def test_intent_identity_is_frozen_and_target_is_only_in_digest():
    original = intent()
    other_target = intent(target="another-order")
    assert original.identity == ("synthetic-actor", "edit", OPERATION_ID)
    assert original.identity == other_target.identity
    assert original.payload_digest != other_target.payload_digest
    assert len(original.payload_digest) == 64
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        original.payload_digest = "changed"
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        original.identity = ("other", "edit", OPERATION_ID)
    with pytest.raises(TypeError):
        original.identity[0] = "other"


@pytest.mark.parametrize("operation", tuple(COMMAND_MODELS))
def test_identical_intents_compare_true(operation):
    target = None if operation == "create" else "synthetic-order"
    assert compare_mutation_intent(intent(operation, target=target), intent(operation, target=target)) is True


@pytest.mark.parametrize("change", ["target", "actor", "type", "version", "payload", "operation_id"])
def test_cross_intent_conflicts_are_value_errors(change):
    baseline = intent()
    candidate = {
        "target": lambda: intent(target="different-order"),
        "actor": lambda: intent(actor="different-actor"),
        "type": lambda: intent("ready"),
        "version": lambda: intent(expected_order_version=1),
        "payload": lambda: intent(changes={"notes": "Different correction"}),
        "operation_id": lambda: intent(client_operation_id="qa_operation_0002"),
    }[change]()
    assert issubclass(MutationIntentConflict, ValueError)
    if change in ("target", "version", "payload"):
        assert baseline.identity == candidate.identity
        assert baseline.payload_digest != candidate.payload_digest
    else:
        assert baseline.identity != candidate.identity
    with pytest.raises(MutationIntentConflict):
        compare_mutation_intent(baseline, candidate)
    with pytest.raises(MutationIntentConflict):
        compare_mutation_intent(candidate, baseline)


def test_create_omitted_and_explicit_defaults_have_same_fingerprint():
    minimal = order_payload()
    explicit = StrictOrderCreate.model_validate(minimal).model_dump(mode="json")
    first = intent("create", target=None, order=minimal)
    second = intent("create", target=None, order=explicit)
    assert compare_mutation_intent(first, second) is True
    explicit["items"][0]["quantity"] = 3
    with pytest.raises(MutationIntentConflict):
        compare_mutation_intent(first, intent("create", target=None, order=explicit))


def test_fingerprint_normalizes_trimming_key_order_and_numeric_representation():
    first = intent("create", target=None, order=order_payload(total_amount=25))
    second_payload = order_payload(customer_name="  Synthetic Customer  ", total_amount=25.0)
    second_payload["items"][0]["name"] = "  Synthetic Meal  "
    second_payload = dict(reversed(list(second_payload.items())))
    second = intent("create", target=None, order=second_payload)
    assert compare_mutation_intent(first, second) is True
    status_minimal = intent("status")
    assert compare_mutation_intent(status_minimal, intent("status", cancellation_reason=None)) is True


@pytest.mark.parametrize("cleared", [{"notes": None}, {"customer_latitude": None, "customer_longitude": None}])
def test_unset_correction_and_explicit_null_have_different_digest(cleared):
    unchanged = intent(changes={"customer_name": "Updated Customer"})
    clearing = intent(changes={"customer_name": "Updated Customer", **cleared})
    assert unchanged.identity == clearing.identity
    assert unchanged.payload_digest != clearing.payload_digest
    with pytest.raises(MutationIntentConflict):
        compare_mutation_intent(unchanged, clearing)


def test_nested_correction_fields_set_survives_intent_revalidation():
    patch = OrderCorrections(customer_name="  Updated Customer  ")
    command = EditOrderCommand(
        client_operation_id=OPERATION_ID, expected_order_version=0, changes=patch,
    )
    original_fields = patch.model_fields_set.copy()
    built = build_mutation_intent("synthetic-actor", "edit", "synthetic-order", command)
    assert compare_mutation_intent(built, intent(changes={"customer_name": "Updated Customer"})) is True
    assert command.changes.model_fields_set == original_fields == {"customer_name"}
    assert command.changes.model_dump(exclude_unset=True) == {"customer_name": "Updated Customer"}
    with pytest.raises(MutationIntentConflict):
        compare_mutation_intent(built, intent(changes={"customer_name": "Updated Customer", "notes": None}))


@pytest.mark.parametrize("operation", VERSIONED_OPERATIONS)
def test_every_versioned_operation_binds_target_and_version_in_digest(operation):
    original = intent(operation)
    for candidate in (intent(operation, target="another-order"), intent(operation, expected_order_version=MAX_VERSION)):
        assert original.identity == candidate.identity
        assert original.payload_digest != candidate.payload_digest
        with pytest.raises(MutationIntentConflict):
            compare_mutation_intent(original, candidate)


@pytest.mark.parametrize("operation", VERSIONED_OPERATIONS)
@pytest.mark.parametrize("target", [None, "", "   ", "x" * 121, True, 123])
def test_noncreate_intent_requires_bounded_nonblank_target(operation, target):
    with pytest.raises(ValueError):
        intent(operation, target=target)


@pytest.mark.parametrize("target", ["", "synthetic-order", True, 0])
def test_create_intent_requires_none_target(target):
    with pytest.raises(ValueError):
        intent("create", target=target)


@pytest.mark.parametrize("operation", tuple(COMMAND_MODELS))
def test_intent_operation_must_match_command_class(operation):
    wrong_operation = "ready" if operation != "ready" else "edit"
    command = COMMAND_MODELS[wrong_operation].model_validate(command_payload(wrong_operation))
    with pytest.raises(ValueError):
        build_mutation_intent("synthetic-actor", operation, None if operation == "create" else "synthetic-order", command)


@pytest.mark.parametrize("operation", ["unknown", "CREATE", "preparation", "", None, True, {}])
def test_intent_rejects_unknown_operation_type(operation):
    command = ReadyOrderCommand.model_validate(command_payload("ready"))
    with pytest.raises(ValueError):
        build_mutation_intent("synthetic-actor", operation, "synthetic-order", command)


@pytest.mark.parametrize("actor", [None, "", "   ", True, 123])
def test_intent_rejects_missing_or_nonstring_authenticated_actor(actor):
    with pytest.raises(ValueError):
        intent(actor=actor)


@pytest.mark.parametrize("state", ["applied", "replayed", "pending", "rejected"])
def test_valid_result_states_round_trip(state):
    result = MutationResult.model_validate(result_payload(state))
    assert MutationResult.model_validate_json(result.model_dump_json()) == result
    assert result.state == state


@pytest.mark.parametrize("state", ["applied", "replayed"])
@pytest.mark.parametrize("overrides", [{"order_id": None}, {"order_version": None}, {"error_code": "ERROR"},
                                      {"retry_after_seconds": 1}, {"order_id": "   "}])
def test_committed_results_cannot_lack_identity_or_claim_failure(state, overrides):
    with pytest.raises(ValidationError):
        MutationResult.model_validate(result_payload(state, **overrides))


@pytest.mark.parametrize("value", [True, False, "0", 0.0, -1, MAX_VERSION + 1])
def test_result_version_is_strict_and_bounded(value):
    with pytest.raises(ValidationError):
        MutationResult.model_validate(result_payload("applied", order_version=value))


@pytest.mark.parametrize("state", ["applied", "replayed"])
@pytest.mark.parametrize("version", [0, MAX_VERSION])
def test_committed_result_version_edges(state, version):
    assert MutationResult.model_validate(result_payload(state, order_version=version)).order_version == version


@pytest.mark.parametrize("overrides", [{"retry_after_seconds": None}, {"retry_after_seconds": 0}, {"retry_after_seconds": 61},
                                      {"retry_after_seconds": True}, {"retry_after_seconds": "1"}, {"retry_after_seconds": 1.0},
                                      {"order_id": "synthetic-order"}, {"order_version": 0}, {"error_code": "ERROR"}])
def test_pending_results_require_strict_retry_and_no_committed_or_error_fields(overrides):
    with pytest.raises(ValidationError):
        MutationResult.model_validate(result_payload("pending", **overrides))


def test_pending_retry_upper_boundary():
    assert MutationResult.model_validate(result_payload("pending", retry_after_seconds=60)).retry_after_seconds == 60


@pytest.mark.parametrize("overrides", [{"error_code": None}, {"error_code": ""}, {"error_code": " "}, {"error_code": "E" * 65},
                                      {"error_code": True}, {"order_id": "synthetic-order"}, {"order_version": 0},
                                      {"retry_after_seconds": 1}])
def test_rejected_results_require_bounded_error_and_no_order_or_retry(overrides):
    with pytest.raises(ValidationError):
        MutationResult.model_validate(result_payload("rejected", **overrides))


@pytest.mark.parametrize("code", ["E", "E" * 64])
def test_rejection_error_code_boundaries(code):
    assert MutationResult.model_validate(result_payload("rejected", error_code=code)).error_code == code


@pytest.mark.parametrize("overrides", [{"state": "success"}, {"state": True}, {"client_operation_id": "short"},
                                      {"order_id": "x" * 121}, {"order_id": 123}, {"unexpected": True}])
def test_result_rejects_invalid_envelope(overrides):
    with pytest.raises(ValidationError):
        MutationResult.model_validate(result_payload("applied", **overrides))


def test_legacy_models_remain_permissive_and_unversioned():
    legacy_item = OrderItem(name="Meal", quantity="2", price="1.5")
    assert legacy_item.quantity == 2
    assert legacy_item.price == 1.5
    legacy = OrderCreate.model_validate(order_payload(customer_latitude=1, total_amount="25"))
    assert legacy.customer_longitude is None
    assert legacy.total_amount == 25
    assert "expected_order_version" not in OrderCreate.model_fields
    assert PreparationTime(preparation_time="30").preparation_time == 30
    assert UpdateOrderStatus(status="NEW").status == "NEW"
    assert UpdateOrderStatus(status="CANCELLED").cancellation_reason is None
    with pytest.raises(ValidationError):
        StrictOrderCreate.model_validate(order_payload(customer_latitude=1, total_amount="25"))


@pytest.fixture
def contract_client():
    # Contract-only echo endpoints: not real mutation routes or authorization.
    app = FastAPI()

    def echo_endpoint(model):
        async def echo(command: model):
            return command
        return echo

    for operation, model in COMMAND_MODELS.items():
        app.add_api_route(
            "/contracts/" + operation, echo_endpoint(model), methods=["POST"],
            response_model=model, response_model_exclude_unset=True,
        )

    @app.post("/contracts/result", response_model=MutationResult)
    async def result_contract(payload: dict):
        return payload

    return InMemoryContractClient(app)


class InMemoryContractClient:
    """Drive non-suspending contract ASGI calls without a Windows socketpair."""

    def __init__(self, app):
        self.app = app

    def post(self, path, *, json):
        body = jsonlib.dumps(json, allow_nan=False).encode("utf-8")
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": path, "raw_path": path.encode("ascii"), "query_string": b"",
            "root_path": "", "headers": [(b"content-type", b"application/json")],
            "client": ("synthetic-client", 0), "server": ("synthetic.invalid", 80),
        }
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                raise AssertionError("Contract unexpectedly requested streaming input")
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        # These async endpoints contain no I/O. Any suspension is a harness error,
        # not permission to create an event loop or relax the runner network guard.
        call = self.app(scope, receive, send)
        try:
            call.send(None)
        except StopIteration:
            pass
        except ResponseValidationError:
            assert any(message.get("status") == 500 for message in messages)
        else:
            raise AssertionError("Contract unexpectedly suspended outside in-memory ASGI")
        finally:
            call.close()
        starts = [message for message in messages if message["type"] == "http.response.start"]
        assert len(starts) == 1
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return httpx.Response(starts[0]["status"], headers=starts[0]["headers"], content=content)


@pytest.mark.parametrize("operation", tuple(COMMAND_MODELS))
def test_synthetic_http_accepts_each_valid_command(contract_client, operation):
    response = contract_client.post("/contracts/" + operation, json=command_payload(operation))
    assert response.status_code == 200
    assert response.json()["client_operation_id"] == OPERATION_ID
    assert COMMAND_MODELS[operation].model_validate(response.json()).model_dump() == COMMAND_MODELS[operation].model_validate(command_payload(operation)).model_dump()


@pytest.mark.parametrize("changes", [{"customer_name": "Updated Customer"},
                                    {"customer_name": "Updated Customer", "notes": None},
                                    {"customer_latitude": None, "customer_longitude": None}])
def test_synthetic_http_patch_echo_preserves_omission_and_explicit_null(contract_client, changes):
    response = contract_client.post("/contracts/edit", json=command_payload("edit", changes=changes))
    assert response.status_code == 200
    assert response.json()["changes"] == changes
    assert EditOrderCommand.model_validate(response.json()).changes.model_fields_set == set(changes)


@pytest.mark.parametrize("operation,overrides", [
    ("create", {"order": order_payload(items=[{"name": "Meal", "quantity": True, "price": 1}])}),
    ("create", {"order": order_payload(customer_name=" x ")}),
    ("create", {"order": order_payload(customer_latitude=1)}),
    ("edit", {"changes": {"notes": "ok", "status": "DELIVERED"}}),
    ("edit", {"changes": {"customer_latitude": None}}),
    ("assign", {"driver_id": "   "}),
    ("preparing", {"preparation_time": "30"}),
    ("ready", {"expected_order_version": True}),
    ("ready", {"client_operation_id": " " + OPERATION_ID}),
    ("status", {"status": "CANCELLED", "cancellation_reason": "  "}),
    ("status", {"status": "ASSIGNED"}),
])
def test_synthetic_http_rejects_invalid_commands_before_echo(contract_client, operation, overrides):
    response = contract_client.post("/contracts/" + operation, json=command_payload(operation, **overrides))
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors
    assert all(error["loc"][0] == "body" for error in errors)


@pytest.mark.parametrize("state", ["applied", "replayed", "pending", "rejected"])
def test_synthetic_http_serializes_valid_results(contract_client, state):
    response = contract_client.post("/contracts/result", json=result_payload(state))
    assert response.status_code == 200
    parsed = MutationResult.model_validate(response.json())
    assert parsed.state == state
    if state in ("pending", "rejected"):
        assert parsed.order_id is None and parsed.order_version is None


@pytest.mark.parametrize("payload", [result_payload("applied", order_version=None),
                                   result_payload("replayed", error_code="ERROR"),
                                   result_payload("pending", order_id="synthetic-order"),
                                   result_payload("pending", retry_after_seconds=True),
                                   result_payload("rejected", retry_after_seconds=1)])
def test_synthetic_http_refuses_invalid_outcome_as_success(contract_client, payload):
    response = contract_client.post("/contracts/result", json=payload)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


# Review regressions intentionally use default serialization, with no exclusion
# flags. Earlier tests and their explicitly scoped echo fixture remain unchanged.
REVIEW_PATCHES = [
    pytest.param({"notes": "Synthetic note"}, id="notes-only"),
    pytest.param({"customer_name": "Updated Customer"}, id="name-only"),
    pytest.param({"notes": None}, id="notes-null"),
    pytest.param({"customer_latitude": None, "customer_longitude": None}, id="coordinates-null"),
]


def default_model_roundtrip(model, serialization):
    if serialization == "python":
        return type(model).model_validate(model.model_dump())
    if serialization == "json-dict":
        return type(model).model_validate(model.model_dump(mode="json"))
    return type(model).model_validate_json(model.model_dump_json())


def assert_edit_roundtrip_preserves_intent(original, restored):
    assert restored.changes.model_fields_set == original.changes.model_fields_set
    assert restored.changes.model_dump(exclude_unset=True) == original.changes.model_dump(exclude_unset=True)
    before = build_mutation_intent("synthetic-actor", "edit", "synthetic-order", original)
    after = build_mutation_intent("synthetic-actor", "edit", "synthetic-order", restored)
    assert before.identity == after.identity
    assert before.payload_digest == after.payload_digest
    assert compare_mutation_intent(before, after) is True


@pytest.mark.parametrize("changes", REVIEW_PATCHES)
@pytest.mark.parametrize("serialization", ["python", "json-dict", "json-string"])
def test_review_default_edit_serialization_preserves_patch_and_digest(changes, serialization):
    original = EditOrderCommand.model_validate(command_payload("edit", changes=changes))
    restored = default_model_roundtrip(original, serialization)
    assert_edit_roundtrip_preserves_intent(original, restored)


@pytest.mark.parametrize("changes", REVIEW_PATCHES)
@pytest.mark.parametrize("serialization", ["python", "json-dict", "json-string"])
def test_review_default_correction_serialization_preserves_patch_and_digest(changes, serialization):
    patch = OrderCorrections.model_validate(changes)
    restored_patch = default_model_roundtrip(patch, serialization)
    assert restored_patch.model_fields_set == patch.model_fields_set == set(changes)
    original = EditOrderCommand.model_validate(command_payload("edit", changes=patch))
    restored = EditOrderCommand.model_validate(command_payload("edit", changes=restored_patch))
    assert_edit_roundtrip_preserves_intent(original, restored)


@pytest.fixture
def default_edit_response_client():
    app = FastAPI()

    @app.post("/default-edit", response_model=EditOrderCommand)
    async def default_edit(command: EditOrderCommand):
        return command

    return InMemoryContractClient(app)


@pytest.mark.parametrize("changes", REVIEW_PATCHES)
def test_review_default_fastapi_response_model_preserves_patch_and_digest(default_edit_response_client, changes):
    payload = command_payload("edit", changes=changes)
    original = EditOrderCommand.model_validate(payload)
    response = default_edit_response_client.post("/default-edit", json=payload)
    assert response.status_code == 200
    restored = EditOrderCommand.model_validate(response.json())
    assert response.json()["changes"] == changes
    assert_edit_roundtrip_preserves_intent(original, restored)


ZERO_DIGEST_CASES = [
    pytest.param("create", "total_amount", id="total-amount"),
    pytest.param("create", "subtotal_amount", id="subtotal-amount"),
    pytest.param("create", "delivery_fee", id="delivery-fee"),
    pytest.param("create", "item-price", id="nested-price"),
    pytest.param("create", "customer_latitude", id="create-latitude"),
    pytest.param("create", "customer_longitude", id="create-longitude"),
    pytest.param("edit", "customer_latitude", id="edit-latitude"),
    pytest.param("edit", "customer_longitude", id="edit-longitude"),
]


def numeric_review_intent(operation, field, value):
    if operation == "edit":
        changes = {"customer_latitude": 0.0, "customer_longitude": 0.0}
        changes[field] = value
        return intent("edit", changes=changes)
    payload = order_payload(customer_latitude=0.0, customer_longitude=0.0)
    if field == "item-price":
        payload["items"][0]["price"] = value
    else:
        payload[field] = value
    return intent("create", target=None, order=payload)


@pytest.mark.parametrize("operation,field", ZERO_DIGEST_CASES)
def test_review_signed_zero_is_equivalent_in_digest(operation, field):
    positive = numeric_review_intent(operation, field, 0.0)
    negative = numeric_review_intent(operation, field, -0.0)
    integer = numeric_review_intent(operation, field, 0)
    assert positive.identity == negative.identity == integer.identity
    assert positive.payload_digest == negative.payload_digest == integer.payload_digest
    assert compare_mutation_intent(positive, negative) is True
    assert compare_mutation_intent(positive, integer) is True


@pytest.mark.parametrize("operation,field", ZERO_DIGEST_CASES)
def test_review_zero_canonicalization_does_not_merge_distinct_nonzero_values(operation, field):
    first = numeric_review_intent(operation, field, 1.0)
    adjacent = numeric_review_intent(operation, field, 1.0000000000000002)
    zero = numeric_review_intent(operation, field, 0.0)
    candidates = [adjacent, zero]
    if field.startswith("customer_"):
        candidates.append(numeric_review_intent(operation, field, -1.0))
    for candidate in candidates:
        assert first.identity == candidate.identity
        assert first.payload_digest != candidate.payload_digest
        with pytest.raises(MutationIntentConflict):
            compare_mutation_intent(first, candidate)
