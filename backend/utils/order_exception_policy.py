"""Deterministic, side-effect-free L5C1 assessment of internal resolved facts.

No resolver, authorization, admission, persistence or payment is implemented.
Malformed input raises pydantic.ValidationError; absent or incompatible facts
return unavailable. Missing pricing never changes valid threshold eligibility.
"""

from models.order_exception_policy import (
    AddressChangePolicyInput, CancellationPolicyInput, EvidenceReference, ExceptionPolicyResult,
)


def _provenance_reason(proof, context, fact_at=None):
    if proof is None:
        return "PROVENANCE_MISSING"
    if proof.kind != context.evidence_mode:
        return "PROVENANCE_MODE_MISMATCH"
    if not proof.observed_at <= proof.resolved_at <= context.as_of:
        return "PROVENANCE_TIME_INVALID"
    if fact_at is not None and proof.observed_at > fact_at:
        return "PROVENANCE_OBSERVED_AFTER_FACT"
    return None


def _add_proof(reasons, refs, proof, context, fact_at=None):
    reason = _provenance_reason(proof, context, fact_at)
    if reason:
        reasons.append(reason)
    if proof is not None:
        refs.append((proof.evidence_ref, proof.evidence_digest))


def _reference_conflict(refs):
    """One immutable reference may support multiple facts, but only one digest."""
    seen = {}
    for reference, digest in refs:
        if reference in seen and seen[reference] != digest:
            return True
        seen[reference] = digest
    return False


def _distinct_locations(left, right):
    # An ID with different digests or a digest with different IDs is ambiguous.
    return (left.location_id != right.location_id
            and left.location_digest != right.location_digest)


def _pricing(request, eligibility, cancellation, fact_refs):
    if eligibility == "unavailable":
        return None, None, []
    if eligibility == "zero":
        return 0, None, []
    context, mapping, basis = request.context, request.zone1_mapping, request.courier_basis
    reasons = []
    if context.tariff_version is None:
        reasons.append("TARIFF_VERSION_UNAVAILABLE")
    if mapping is None:
        reasons.append("ZONE1_MAPPING_MISSING")
    else:
        if (mapping.restaurant_id != context.binding.restaurant_id
                or mapping.tariff_version != context.tariff_version):
            reasons.append("ZONE1_MAPPING_BINDING_MISMATCH")
        reason = _provenance_reason(mapping.provenance, context)
        if reason:
            reasons.append("ZONE1_MAPPING_" + reason)
    if basis is None:
        reasons.append("COURIER_BASIS_MISSING")
    else:
        if (basis.restaurant_id != context.binding.restaurant_id
                or basis.tariff_version != context.tariff_version
                or (mapping is not None and basis.zone1_id != mapping.zone1_id)):
            reasons.append("COURIER_BASIS_BINDING_MISMATCH")
        reason = _provenance_reason(basis.provenance, context)
        if reason:
            reasons.append("COURIER_BASIS_" + reason)
    combined_refs = list(fact_refs)
    for item in (mapping, basis):
        if item is not None and item.provenance is not None:
            combined_refs.append((item.provenance.evidence_ref, item.provenance.evidence_digest))
    if _reference_conflict(combined_refs):
        reasons.append("PRICING_EVIDENCE_REFERENCE_CONFLICT")
    if reasons:
        return None, None, reasons
    if cancellation and basis.courier_remuneration_bani % 2:
        return None, basis, ["MONETARY_ROUNDING_UNRESOLVED"]
    amount = basis.courier_remuneration_bani
    return amount // 2 if cancellation else amount, basis, []


def _result(request, eligibility, reasons, refs, cancellation):
    amount, basis, pricing_reasons = _pricing(request, eligibility, cancellation, refs)
    reasons.extend(pricing_reasons)
    if not cancellation:
        reasons.append("RESTAURANT_TRANSPORT_TARIFF_UNAVAILABLE")
    if amount is None:
        pricing_status = "unavailable"
    else:
        pricing_status = "complete" if cancellation else "partial"
    for item in (request.zone1_mapping, request.courier_basis) if eligibility == "eligible" else ():
        if item is not None and item.provenance is not None:
            refs.append((item.provenance.evidence_ref, item.provenance.evidence_digest))
    return ExceptionPolicyResult(
        operation="pre_pickup_cancellation" if cancellation else "post_arrival_address_change",
        evidence_mode=request.context.evidence_mode,
        eligibility=eligibility,
        courier_amount_bani=amount,
        restaurant_bears_courier_compensation=None if eligibility == "unavailable" else True,
        restaurant_transport_status="not_applicable" if cancellation else "unavailable",
        pricing_status=pricing_status,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_refs=tuple(EvidenceReference(evidence_ref=ref, evidence_digest=digest)
                            for ref, digest in dict.fromkeys(refs)),
        courier_basis=basis,
    )


def evaluate_cancellation(request: CancellationPolicyInput) -> ExceptionPolicyResult:
    """Evaluate a pre-pickup cancellation; never cancel or authorize an order.

    Revalidation also rejects unsafe model_construct/model_copy values. Evidence
    may be resolved post-factum, provided resolved_at is not beyond as_of.
    """
    request = CancellationPolicyInput.model_validate(request)
    context, reasons, refs = request.context, [], []
    if not context.assigned_at <= request.cancelled_at <= context.as_of:
        reasons.append("CANCELLATION_TIME_INVALID")
    if request.state_before not in ("ASSIGNED", "ACCEPTED") or request.picked_up_at is not None:
        reasons.append("NOT_PRE_PICKUP")
    evidence = request.evidence
    if evidence is None:
        return _result(request, "unavailable", reasons + ["CANCELLATION_EVIDENCE_MISSING"], refs, True)
    departure, route, progress = evidence.departure, evidence.route, evidence.progress
    for name, fact in (("DEPARTURE", departure), ("ROUTE", route), ("PROGRESS", progress)):
        if fact is None:
            reasons.append(name + "_MISSING")
            continue
        if fact.binding != context.binding:
            reasons.append(name + "_BINDING_MISMATCH")
        fact_at = departure.departed_at if name == "DEPARTURE" else request.cancelled_at
        _add_proof(reasons, refs, fact.provenance, context, fact_at)
    if departure is not None:
        if not context.assigned_at <= departure.departed_at <= request.cancelled_at:
            reasons.append("DEPARTURE_TIME_INVALID")
        if departure.provenance is not None and departure.provenance.observed_at != departure.departed_at:
            reasons.append("DEPARTURE_OBSERVATION_MISMATCH")
    if route is not None:
        if route.total is None or route.total.raw_units == 0:
            reasons.append("POSITIVE_ROUTE_TOTAL_REQUIRED")
        if route.restaurant_location != request.restaurant_location:
            reasons.append("ROUTE_RESTAURANT_MISMATCH")
        if departure is not None and (route.departure_id != departure.departure_id or route.origin != departure.origin):
            reasons.append("ROUTE_DEPARTURE_MISMATCH")
    if progress is not None:
        if progress.travelled is None:
            reasons.append("TRAVELLED_DISTANCE_MISSING")
        if progress.cancellation_id != request.cancellation_id:
            reasons.append("PROGRESS_CANCELLATION_MISMATCH")
        if progress.measured_until != request.cancelled_at:
            reasons.append("PROGRESS_NOT_AT_CANCELLATION")
        if progress.provenance is not None and progress.provenance.observed_at != progress.measured_until:
            reasons.append("PROGRESS_OBSERVATION_MISMATCH")
        if departure is not None and (progress.departure_id != departure.departure_id or progress.measured_until < departure.departed_at):
            reasons.append("PROGRESS_DEPARTURE_MISMATCH")
        if route is not None and (progress.route_id != route.route_id or progress.route_digest != route.route_digest):
            reasons.append("PROGRESS_ROUTE_MISMATCH")
    if _reference_conflict(refs):
        reasons.append("EVIDENCE_REFERENCE_CONFLICT")
    if reasons:
        return _result(request, "unavailable", reasons, refs, True)
    # Exact cross-products permit different declared precision without floats.
    eligible = (2 * progress.travelled.raw_units * 10**route.total.decimal_places
                > route.total.raw_units * 10**progress.travelled.decimal_places)
    return _result(request, "eligible" if eligible else "zero", [
        "TRAVELLED_ABOVE_HALF" if eligible else "TRAVELLED_AT_OR_BELOW_HALF"
    ], refs, True)


def evaluate_address_change(request: AddressChangePolicyInput) -> ExceptionPolicyResult:
    """Assess one change, retaining prior zero changes in the slot count.

    The second segment begins at new1; a second arrival is not required. The
    original arrival and resolved predecessor must remain bound and temporal.
    """
    request = AddressChangePolicyInput.model_validate(request)
    context, reasons, refs = request.context, [], []
    if request.state != "PICKED_UP":
        reasons.append("ADDRESS_CHANGE_STATE_INVALID")
    if not context.assigned_at <= request.picked_up_at <= request.changed_at <= context.as_of:
        reasons.append("ADDRESS_CHANGE_TIME_INVALID")
    arrival, segment = request.original_arrival, request.segment
    if arrival is None:
        reasons.append("ORIGINAL_ARRIVAL_MISSING")
    else:
        if arrival.binding != context.binding or arrival.original_address != request.original_address:
            reasons.append("ORIGINAL_ARRIVAL_BINDING_MISMATCH")
        if not request.picked_up_at <= arrival.arrived_at <= request.changed_at:
            reasons.append("ORIGINAL_ARRIVAL_TIME_INVALID")
        _add_proof(reasons, refs, arrival.provenance, context, arrival.arrived_at)
        if arrival.provenance is not None and arrival.provenance.observed_at != arrival.arrived_at:
            reasons.append("ARRIVAL_OBSERVATION_MISMATCH")
    if not _distinct_locations(request.current_address, request.target_address):
        reasons.append("TARGET_NO_OP_OR_AMBIGUOUS")
    # Reusing the original ID requires the original digest (A -> B -> A is valid).
    original, target = request.original_address, request.target_address
    if (original.location_id == target.location_id) != (original.location_digest == target.location_digest):
        reasons.append("ORIGINAL_TARGET_IDENTITY_AMBIGUOUS")
    if len(request.history) != request.change_ordinal - 1:
        reasons.append("ADDRESS_HISTORY_COUNT_MISMATCH")
    if len(request.history) >= 2:
        reasons.append("ADDRESS_CHANGE_LIMIT_EXCEEDED")
    if request.change_ordinal == 1:
        if request.predecessor_id is not None or request.current_address != original:
            reasons.append("FIRST_CHANGE_ORIGIN_INVALID")
    elif len(request.history) == 1:
        prior = request.history[0]
        if (prior.change_ordinal != 1 or prior.change_id != request.predecessor_id
                or prior.change_id == request.change_id or prior.binding != context.binding
                or prior.original_address != original or prior.source_address != original
                or prior.target_address != request.current_address
                or not _distinct_locations(prior.source_address, prior.target_address)):
            reasons.append("PREDECESSOR_CHAIN_INVALID")
        if not request.picked_up_at <= prior.changed_at <= request.changed_at:
            reasons.append("PREDECESSOR_TIME_INVALID")
        if arrival is not None:
            if (prior.original_arrival_id != arrival.arrival_id
                    or (arrival.provenance is not None and prior.original_arrival_digest != arrival.provenance.evidence_digest)):
                reasons.append("PREDECESSOR_ARRIVAL_MISMATCH")
            if arrival.arrived_at > prior.changed_at:
                reasons.append("PREDECESSOR_BEFORE_ORIGINAL_ARRIVAL")
        _add_proof(reasons, refs, prior.provenance, context, prior.changed_at)
        if prior.provenance is not None and prior.provenance.observed_at != prior.changed_at:
            reasons.append("PREDECESSOR_OBSERVATION_MISMATCH")
    if segment is None:
        reasons.append("ADDRESS_ROAD_SEGMENT_MISSING")
    else:
        if (segment.binding != context.binding or segment.change_id != request.change_id
                or segment.source_address != request.current_address
                or segment.target_address != request.target_address):
            reasons.append("ADDRESS_ROAD_SEGMENT_BINDING_MISMATCH")
        if segment.distance is None:
            reasons.append("ADDRESS_ROAD_DISTANCE_MISSING")
        _add_proof(reasons, refs, segment.provenance, context, request.changed_at)
    if _reference_conflict(refs):
        reasons.append("EVIDENCE_REFERENCE_CONFLICT")
    if reasons:
        return _result(request, "unavailable", reasons, refs, False)
    eligible = segment.distance.raw_units > 2000 * 10**segment.distance.decimal_places
    return _result(request, "eligible" if eligible else "zero", [
        "SEGMENT_ABOVE_TWO_KM" if eligible else "SEGMENT_AT_OR_BELOW_TWO_KM"
    ], refs, False)
