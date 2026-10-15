"""Synthetic policy-only tests; no server, database, network or physical proof."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo

import pytest
from pydantic import ValidationError

from models.order_exception_policy import (
    AddressChangePolicyInput, CancellationPolicyInput, ExceptionPolicyResult,
    RawRoadDistance, SyntheticProvenance,
)
from utils.order_exception_policy import evaluate_address_change, evaluate_cancellation


T = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)
BINDING = dict(order_id="order-synthetic", restaurant_id="restaurant-synthetic",
               driver_id="driver-synthetic", assignment_id="assignment-synthetic")
A = dict(location_id="address-original", location_digest="a" * 64)
B = dict(location_id="address-new1", location_digest="b" * 64)
C = dict(location_id="address-new2", location_digest="c" * 64)


def instant(minutes):
    return T + timedelta(minutes=minutes)


def proof(ref, minute):
    return dict(kind="synthetic_fixture", fixture_suite="L5C1-pure",
                evidence_ref=ref, evidence_digest="d" * 64,
                resolver_id="synthetic-resolver", resolver_version="fixture-v1",
                method_id="synthetic-contract-fixture", observed_at=instant(minute),
                resolved_at=instant(9))


def distance(units, decimals=0):
    return dict(raw_units=units, decimal_places=decimals)


def common(bani=1600):
    return dict(
        context=dict(binding=deepcopy(BINDING), assigned_at=T, as_of=instant(10),
                     tariff_version="explicit-v1", evidence_mode="synthetic_fixture"),
        zone1_mapping=dict(restaurant_id=BINDING["restaurant_id"],
                           tariff_version="explicit-v1", zone1_id="canonical-zone1",
                           provenance=proof("zone1-mapping", 0)),
        courier_basis=dict(restaurant_id=BINDING["restaurant_id"],
                           tariff_version="explicit-v1", zone1_id="canonical-zone1",
                           basis_kind="courier_remuneration", currency="RON",
                           courier_remuneration_bani=bani, provenance=proof("courier-basis", 0)),
    )


def cancellation(units=5001, decimals=0, bani=1600, total=10000, total_decimals=0):
    value = common(bani)
    value.update(
        cancellation_id="cancel-1", cancelled_at=instant(5), state_before="ACCEPTED",
        restaurant_location=dict(location_id="restaurant-location", location_digest="e" * 64),
        evidence=dict(
            departure=dict(binding=deepcopy(BINDING), departure_id="departure-1",
                           origin=deepcopy(A), departed_at=instant(1), provenance=proof("departure", 1)),
            route=dict(binding=deepcopy(BINDING), departure_id="departure-1", route_id="route-1",
                       route_digest="f" * 64, origin=deepcopy(A),
                       restaurant_location=dict(location_id="restaurant-location", location_digest="e" * 64),
                       measurement_kind="departure_to_restaurant_road_route",
                       total=distance(total, total_decimals), provenance=proof("route", 1)),
            progress=dict(binding=deepcopy(BINDING), cancellation_id="cancel-1", departure_id="departure-1",
                          route_id="route-1", route_digest="f" * 64,
                          measurement_kind="actual_eligible_road_progress", measured_until=instant(5),
                          travelled=distance(units, decimals), provenance=proof("progress", 5)),
        ),
    )
    return value


def address(units=2001, decimals=0, bani=1600, second=False, target=None):
    value = common(bani)
    target = deepcopy(target if target is not None else C if second else B)
    current, minute, change_id = (deepcopy(B), 6, "change-2") if second else (deepcopy(A), 5, "change-1")
    value.update(
        change_id=change_id, change_ordinal=2 if second else 1, changed_at=instant(minute),
        picked_up_at=instant(1), state="PICKED_UP", original_address=deepcopy(A),
        current_address=current, target_address=target,
        original_arrival=dict(binding=deepcopy(BINDING), arrival_id="arrival-1",
                              original_address=deepcopy(A), arrived_at=instant(4),
                              fact_kind="original_destination_arrival", provenance=proof("arrival", 4)),
        segment=dict(binding=deepcopy(BINDING), change_id=change_id, source_address=deepcopy(current),
                     target_address=deepcopy(target), measurement_kind="directed_address_road_segment",
                     distance=distance(units, decimals), provenance=proof("segment-" + change_id, minute)),
    )
    if second:
        value.update(predecessor_id="change-1", history=(dict(
            binding=deepcopy(BINDING), change_id="change-1", change_ordinal=1,
            original_address=deepcopy(A), source_address=deepcopy(A), target_address=deepcopy(B),
            original_arrival_id="arrival-1", original_arrival_digest="d" * 64,
            changed_at=instant(5), provenance=proof("admitted-change-1", 5),
        ),))
    return value


def assert_unavailable(result):
    assert result.eligibility == "unavailable"
    assert result.courier_amount_bani is None
    assert result.restaurant_bears_courier_compensation is None
    assert result.pricing_status == "unavailable"


@pytest.mark.parametrize("units,decimals,total,total_decimals,expected", [
    (0, 0, 10000, 0, 0), (4999, 0, 10000, 0, 0), (5000, 0, 10000, 0, 0),
    (5001, 0, 10000, 0, 800), (4999999, 3, 10000, 0, 0),
    (5000000, 3, 10000, 0, 0), (5000001, 3, 10000, 0, 800),
    (5000500, 3, 10001, 0, 0), (5000501, 3, 10001, 0, 800),
    (5001, 0, 10000000, 3, 800), (10001, 0, 10000, 0, 800),
    (5000000001, 6, 10000, 0, 800),
])
def test_exact_cancellation_threshold(units, decimals, total, total_decimals, expected):
    result = evaluate_cancellation(cancellation(units, decimals, total=total, total_decimals=total_decimals))
    assert result.courier_amount_bani == expected
    assert result.eligibility == ("eligible" if expected else "zero")
    assert result.restaurant_bears_courier_compensation is True
    assert result.restaurant_transport_surcharge_bani is None
    assert result.restaurant_transport_status == "not_applicable"


@pytest.mark.parametrize("units,decimals,expected", [
    (0, 0, 0), (1999, 0, 0), (2000, 0, 0), (2001, 0, 1600),
    (1999999, 3, 0), (2000000, 3, 0), (2000001, 3, 1600),
    (2500, 0, 1600), (2999, 0, 1600), (2000000001, 6, 1600),
])
def test_exact_independent_address_threshold(units, decimals, expected):
    result = evaluate_address_change(address(units, decimals))
    assert result.courier_amount_bani == expected
    assert result.eligibility == ("eligible" if expected else "zero")
    assert result.restaurant_transport_surcharge_bani is None
    assert result.restaurant_transport_status == "unavailable"
    assert result.pricing_status == "partial"


@pytest.mark.parametrize("bani,expected", [(1600, 800), (1601, None), (1, None), (0, 0)])
def test_half_bani_never_invents_rounding(bani, expected):
    result = evaluate_cancellation(cancellation(bani=bani))
    assert result.eligibility == "eligible"
    assert result.courier_amount_bani == expected
    assert result.courier_basis.courier_remuneration_bani == bani
    assert ("MONETARY_ROUNDING_UNRESOLVED" in result.reason_codes) == bool(bani % 2)


@pytest.mark.parametrize("bani", [1600, 1601, 1, 0])
def test_address_uses_full_courier_basis(bani):
    result = evaluate_address_change(address(bani=bani))
    assert result.eligibility == "eligible"
    assert result.courier_amount_bani == bani


@pytest.mark.parametrize("make,evaluate", [(cancellation, evaluate_cancellation), (address, evaluate_address_change)])
@pytest.mark.parametrize("field", ["zone1_mapping", "courier_basis"])
def test_missing_pricing_preserves_eligibility(make, evaluate, field):
    value = make()
    value[field] = None
    result = evaluate(value)
    assert result.eligibility == "eligible"
    assert result.courier_amount_bani is None


@pytest.mark.parametrize("make,evaluate", [(cancellation, evaluate_cancellation), (address, evaluate_address_change)])
@pytest.mark.parametrize("field", ["zone1_mapping", "courier_basis"])
@pytest.mark.parametrize("key", ["restaurant_id", "tariff_version", "zone1_id"])
def test_pricing_binding_mismatch_is_not_zero(make, evaluate, field, key):
    value = make()
    value[field][key] = "wrong"
    result = evaluate(value)
    assert result.eligibility == "eligible"
    assert result.courier_amount_bani is None


@pytest.mark.parametrize("make,evaluate", [(cancellation, evaluate_cancellation), (address, evaluate_address_change)])
@pytest.mark.parametrize("bani", [None, 1601])
def test_zero_threshold_does_not_require_pricing(make, evaluate, bani):
    value = make(units=0)
    if bani is None:
        value["courier_basis"] = value["zone1_mapping"] = None
    else:
        value["courier_basis"]["courier_remuneration_bani"] = bani
    result = evaluate(value)
    assert result.eligibility == "zero" and result.courier_amount_bani == 0


@pytest.mark.parametrize("component", ["departure", "route", "progress"])
@pytest.mark.parametrize("binding_key", list(BINDING))
def test_each_cancellation_fact_has_full_binding(component, binding_key):
    value = cancellation(units=0)
    value["evidence"][component]["binding"][binding_key] = "other"
    assert_unavailable(evaluate_cancellation(value))


@pytest.mark.parametrize("component", ["departure", "route", "progress"])
def test_missing_cancellation_facts_and_provenance(component):
    value = cancellation()
    value["evidence"][component]["provenance"] = None
    assert_unavailable(evaluate_cancellation(value))
    value["evidence"][component] = None
    assert_unavailable(evaluate_cancellation(value))


@pytest.mark.parametrize("path,new_value", [
    (("evidence",), None), (("evidence", "route", "total"), distance(0)),
    (("evidence", "progress", "travelled"), None),
    (("evidence", "route", "origin"), B),
    (("evidence", "route", "restaurant_location"), B),
    (("evidence", "route", "departure_id"), "other"),
    (("evidence", "progress", "route_id"), "other"),
    (("evidence", "progress", "route_digest"), "a" * 64),
    (("evidence", "progress", "cancellation_id"), "other"),
    (("evidence", "progress", "measured_until"), instant(4)),
    (("evidence", "departure", "departed_at"), instant(6)),
    (("picked_up_at",), instant(2)), (("state_before",), "PICKED_UP"),
    (("cancelled_at",), instant(11)),
    (("context", "assigned_at"), instant(2)),
])
def test_contradictory_cancellation_never_defaults_zero(path, new_value):
    value = cancellation(units=0)
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = deepcopy(new_value)
    assert_unavailable(evaluate_cancellation(value))


@pytest.mark.parametrize("first,second,expected", [
    (1500, 1500, (0, 0)), (2001, 2001, (1600, 1600)), (1500, 2500, (0, 1600)),
])
def test_two_changes_are_independent_and_zero_still_consumes_slot(first, second, expected):
    one = evaluate_address_change(address(first))
    two = evaluate_address_change(address(second, second=True))
    assert (one.courier_amount_bani, two.courier_amount_bani) == expected
    # Slot count is admitted history, never the number of positive payments.
    third = address(1500, second=True)
    third["history"] = third["history"] * 2
    assert_unavailable(evaluate_address_change(third))
    third["change_ordinal"] = 3
    with pytest.raises(ValidationError):
        evaluate_address_change(third)


def test_second_change_needs_no_fresh_arrival_and_can_return_to_original():
    value = address(second=True, target=A)
    # Only original arrival exists; second change may occur at the same instant.
    value["changed_at"] = instant(5)
    value["segment"]["provenance"]["observed_at"] = instant(5)
    result = evaluate_address_change(value)
    assert result.eligibility == "eligible" and result.courier_amount_bani == 1600


@pytest.mark.parametrize("component", ["original_arrival", "segment", "history"])
@pytest.mark.parametrize("key", list(BINDING))
def test_address_binding_is_complete(component, key):
    value = address(second=True)
    fact = value[component][0] if component == "history" else value[component]
    fact["binding"][key] = "other"
    assert_unavailable(evaluate_address_change(value))


@pytest.mark.parametrize("path,new_value", [
    (("original_arrival",), None), (("segment",), None),
    (("segment", "distance"), None), (("segment", "source_address"), A),
    (("segment", "target_address"), B), (("original_arrival", "original_address"), B),
    (("predecessor_id",), "other"), (("history",), ()),
    (("current_address",), C), (("target_address",), B),
    (("history", 0, "change_id"), "change-2"),
    (("history", 0, "change_ordinal"), 2),
    (("history", 0, "source_address"), C),
    (("history", 0, "original_address"), B),
    (("history", 0, "original_arrival_id"), "other"),
    (("history", 0, "original_arrival_digest"), "e" * 64),
    (("history", 0, "changed_at"), instant(7)),
    (("original_arrival", "arrived_at"), instant(6)),
    (("picked_up_at",), instant(7)), (("state",), "DELIVERED"),
    (("target_address", "location_id"), A["location_id"]),
    (("target_address", "location_digest"), A["location_digest"]),
])
def test_address_chain_and_temporal_errors_return_unavailable(path, new_value):
    value = address(units=0, second=True)
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = deepcopy(new_value)
    assert_unavailable(evaluate_address_change(value))


@pytest.mark.parametrize("value", [True, False, 1.0, "2000", float("nan"), float("inf"), -1, 10**15 + 1])
def test_raw_distance_rejects_coercion_and_out_of_bounds(value):
    with pytest.raises(ValidationError):
        RawRoadDistance(raw_units=value, decimal_places=0)


@pytest.mark.parametrize("value", [True, False, 0.0, "0", -1, 7, None])
def test_distance_precision_is_strict_and_bounded(value):
    with pytest.raises(ValidationError):
        RawRoadDistance(raw_units=2000, decimal_places=value)


@pytest.mark.parametrize("value", [True, 1600.0, "1600", -1, None, 100_000_001])
def test_money_is_strict(value):
    with pytest.raises(ValidationError):
        evaluate_cancellation(cancellation(bani=value))


@pytest.mark.parametrize("value", [T.replace(tzinfo=None), "2026-10-14T10:00:00Z", 0, True,
                                   T.replace(year=1899), T.replace(year=9999)])
def test_datetime_requires_bounded_aware_typed_value(value):
    data = cancellation()
    data["context"]["as_of"] = value
    with pytest.raises(ValidationError):
        evaluate_cancellation(data)


def test_different_timezone_same_instant_and_post_factum_resolution():
    value = cancellation()
    baseline = evaluate_cancellation(value)
    value["cancelled_at"] = instant(5).astimezone(timezone(timedelta(hours=3)))
    assert evaluate_cancellation(value) == baseline
    assert value["evidence"]["progress"]["provenance"]["resolved_at"] > value["cancelled_at"]
    value["evidence"]["progress"]["provenance"]["resolved_at"] = instant(11)
    assert_unavailable(evaluate_cancellation(value))


class SyntheticRepeatedHour(tzinfo):
    """Exact synthetic UTC+3/UTC+2 fold, independent of OS timezone data."""

    def utcoffset(self, dt):
        return timedelta(hours=2 if dt.fold else 3)

    def dst(self, dt):
        return timedelta(hours=0 if dt.fold else 1)


def test_repeated_hour_chronology_compares_instants_not_local_wall_time():
    value = cancellation()
    repeated = SyntheticRepeatedHour()
    wall = datetime(2026, 10, 25, 3, 10, tzinfo=repeated)
    # Local 03:10 fold1 is 01:10Z, AFTER 03:20 fold0 = 00:20Z.
    assigned = wall.replace(fold=1)
    departed = wall.replace(minute=15, fold=0)
    cancelled = wall.replace(minute=20, fold=0)
    value["context"].update(assigned_at=assigned, as_of=wall.replace(hour=5, fold=1))
    value["cancelled_at"] = cancelled
    value["evidence"]["departure"]["departed_at"] = departed
    value["evidence"]["progress"]["measured_until"] = cancelled
    for name, at in (("departure", departed), ("route", departed), ("progress", cancelled)):
        value["evidence"][name]["provenance"].update(observed_at=at, resolved_at=wall.replace(hour=4, fold=1))
    result = evaluate_cancellation(value)
    assert_unavailable(result)
    assert "CANCELLATION_TIME_INVALID" in result.reason_codes
    # Switching only assignment to the earlier fold makes all facts coherent.
    value["context"]["assigned_at"] = wall.replace(fold=0)
    assert evaluate_cancellation(value).eligibility == "eligible"


def test_every_nested_datetime_normalizes_to_immutable_utc():
    value = address(second=True)
    offset = timezone(timedelta(hours=3))

    def use_offset(item):
        if isinstance(item, dict):
            return {key: use_offset(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return tuple(use_offset(child) for child in item)
        return item.astimezone(offset) if isinstance(item, datetime) else item

    standard = AddressChangePolicyInput.model_validate(value)
    alternative = AddressChangePolicyInput.model_validate(use_offset(value))
    assert alternative.model_dump_json() == standard.model_dump_json()
    assert alternative.history[0].provenance.observed_at.tzinfo is timezone.utc
    assert evaluate_address_change(alternative) == evaluate_address_change(standard)


@pytest.mark.parametrize("moment", [
    datetime(1900, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    datetime(9998, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-1))),
])
def test_timestamp_bounds_apply_after_utc_normalization(moment):
    value = cancellation()
    value["context"]["as_of"] = moment
    with pytest.raises(ValidationError):
        evaluate_cancellation(value)


@pytest.mark.parametrize("field", ["verified", "approved", "advance_paid_bani", "refund_paid_bani"])
def test_client_authority_flags_or_paid_fields_are_not_accepted(field):
    value = cancellation()
    value["evidence"]["progress"]["provenance"][field] = True
    with pytest.raises(ValidationError):
        evaluate_cancellation(value)


@pytest.mark.parametrize("kind", ["restaurant_to_client", "straight_line", "gps_position", "geocoding"])
def test_wrong_measurement_cannot_substitute_actual_progress(kind):
    value = cancellation()
    value["evidence"]["progress"]["measurement_kind"] = kind
    with pytest.raises(ValidationError):
        evaluate_cancellation(value)


def test_other_price_kind_cannot_replace_courier_basis():
    value = cancellation()
    value["courier_basis"]["basis_kind"] = "restaurant_transport"
    with pytest.raises(ValidationError):
        evaluate_cancellation(value)


@pytest.mark.parametrize("value", ["", " padded", "padded ", "line\nfeed", "x" * 121])
def test_identifiers_are_bounded_unpadded_and_control_free(value):
    data = cancellation()
    data["context"]["binding"]["order_id"] = value
    with pytest.raises(ValidationError):
        evaluate_cancellation(data)


def test_models_results_and_caller_inputs_are_immutable_and_deterministic():
    caller = address(second=True)
    model = AddressChangePolicyInput.model_validate(caller)
    before = model.model_dump_json()
    result = evaluate_address_change(model)
    snapshot = {"zone_id": "original-zone", "advance_paid_bani": None,
                "refund_due_bani": None, "refund_paid_bani": None}
    saved_snapshot = deepcopy(snapshot)
    caller["history"][0]["target_address"]["location_id"] = "external-mutation"
    assert model.model_dump_json() == before
    assert evaluate_address_change(model).model_dump_json() == result.model_dump_json()
    assert snapshot == saved_snapshot
    assert result.advance_paid_bani is result.refund_due_bani is result.refund_paid_bani is None
    assert result.evaluation_kind == "policy_only" and result.evidence_mode == "synthetic_fixture"
    for instance, field, value in [
        (model, "history", ()), (model.history[0], "change_id", "changed"),
        (model.history[0].target_address, "location_id", "changed"),
        (model.context.binding, "order_id", "changed"), (result, "reason_codes", ()),
        (result.courier_basis, "courier_remuneration_bani", 1),
    ]:
        with pytest.raises(ValidationError):
            setattr(instance, field, value)
    assert isinstance(model.history, tuple) and isinstance(result.reason_codes, tuple)
    assert isinstance(result.evidence_refs, tuple)


def test_unsafe_construct_and_copy_are_revalidated_at_entry():
    original = CancellationPolicyInput.model_validate(cancellation())
    bad_distance = RawRoadDistance.model_construct(raw_units=True, decimal_places=0)
    bad_progress = original.evidence.progress.model_copy(update={"travelled": bad_distance})
    bad_evidence = original.evidence.model_copy(update={"progress": bad_progress})
    bad_request = original.model_copy(update={"evidence": bad_evidence})
    with pytest.raises(ValidationError):
        evaluate_cancellation(bad_request)
    bad_basis = original.courier_basis.model_copy(update={"courier_remuneration_bani": -2})
    with pytest.raises(ValidationError):
        evaluate_cancellation(original.model_copy(update={"courier_basis": bad_basis}))


def test_serialized_output_rejects_payment_claims():
    data = evaluate_cancellation(cancellation()).model_dump()
    data["advance_paid_bani"] = 800
    with pytest.raises(ValidationError):
        ExceptionPolicyResult.model_validate(data)


def test_provenance_mode_and_time_cannot_be_used_to_claim_resolved_fixture():
    value = cancellation()
    value["context"]["evidence_mode"] = "internal_resolved"
    assert_unavailable(evaluate_cancellation(value))
    value = cancellation()
    value["evidence"]["route"]["provenance"]["observed_at"] = instant(6)
    assert_unavailable(evaluate_cancellation(value))
    fixture = proof("fixture", 5)
    fixture["resolved_at"] = instant(4)
    # Structural validity is distinct from semantic evidence availability.
    SyntheticProvenance.model_validate(fixture)
    value["evidence"]["route"]["provenance"] = fixture
    assert_unavailable(evaluate_cancellation(value))


@pytest.mark.parametrize("make,evaluate,paths", [
    (cancellation, evaluate_cancellation, (("evidence", "route"), ("evidence", "progress"))),
    (address, evaluate_address_change, (("original_arrival",), ("segment",))),
])
def test_shared_evidence_reference_requires_consistent_digest(make, evaluate, paths):
    value = make()
    proofs = []
    for path in paths:
        fact = value
        for key in path:
            fact = fact[key]
        proofs.append(fact["provenance"])
    for item in proofs:
        item["evidence_ref"] = "same-document"
    # One document may legitimately establish several different facts.
    valid = evaluate(value)
    assert valid.eligibility == "eligible"
    assert len([ref for ref in valid.evidence_refs if ref.evidence_ref == "same-document"]) == 1
    proofs[1]["evidence_digest"] = "e" * 64
    invalid = evaluate(value)
    assert_unavailable(invalid)
    assert "EVIDENCE_REFERENCE_CONFLICT" in invalid.reason_codes
    # Both conflicting references remain inspectable in unavailable output.
    assert len([ref for ref in invalid.evidence_refs if ref.evidence_ref == "same-document"]) == 2


@pytest.mark.parametrize("make,evaluate", [(cancellation, evaluate_cancellation), (address, evaluate_address_change)])
@pytest.mark.parametrize("conflict_with", ["mapping", "fact"])
def test_pricing_reference_conflict_preserves_threshold_eligibility(make, evaluate, conflict_with):
    value = make()
    reference = (value["zone1_mapping"]["provenance"] if conflict_with == "mapping"
                 else value["evidence"]["route"]["provenance"] if make is cancellation
                 else value["segment"]["provenance"])
    value["courier_basis"]["provenance"]["evidence_ref"] = reference["evidence_ref"]
    value["courier_basis"]["provenance"]["evidence_digest"] = "e" * 64
    result = evaluate(value)
    assert result.eligibility == "eligible"
    assert result.courier_amount_bani is None
    assert "PRICING_EVIDENCE_REFERENCE_CONFLICT" in result.reason_codes


@pytest.mark.parametrize("make,evaluate", [(cancellation, evaluate_cancellation), (address, evaluate_address_change)])
@pytest.mark.parametrize("zero", [False, True])
@pytest.mark.parametrize("basis_supplied", [False, True])
def test_missing_selected_tariff_version_does_not_block_threshold(make, evaluate, zero, basis_supplied):
    value = make(units=0) if zero else make()
    del value["context"]["tariff_version"]
    if not basis_supplied:
        value["courier_basis"] = value["zone1_mapping"] = None
    result = evaluate(value)
    assert result.eligibility == ("zero" if zero else "eligible")
    assert result.courier_amount_bani == (0 if zero else None)
    assert ("TARIFF_VERSION_UNAVAILABLE" in result.reason_codes) is not zero
