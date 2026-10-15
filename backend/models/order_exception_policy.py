"""Internal L5C1 policy contracts; these are NOT HTTP request or proof verifiers.

A future trusted server resolver must establish facts, explicit zone-1 mapping,
and tariff selection before constructing these values. A digest or the name
``internal_resolved`` does not authenticate a client assertion. Synthetic
fixtures are explicitly typed and remain synthetic in the result.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=120)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
MoneyBani = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
Ordinal = Annotated[int, Field(strict=True, ge=1, le=2)]


class PolicyContract(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, allow_inf_nan=False,
        revalidate_instances="always",
    )

    @field_validator("*", mode="after")
    @classmethod
    def strict_values(cls, value):
        if isinstance(value, str) and (
            value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Text must be unpadded and have no control characters")
        if isinstance(value, datetime):
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Use an explicit timezone-aware datetime")
            # UTC normalization makes comparisons about instants, including
            # repeated local DST hours (datetime otherwise compares wall time
            # when both values share the same tzinfo object).
            try:
                value = value.astimezone(timezone.utc)
            except (OverflowError, ValueError) as exc:
                raise ValueError("Timestamp cannot be represented in UTC") from exc
            if not 1900 <= value.year <= 9998:
                raise ValueError("Timestamp outside supported technical range")
        return value


class RawRoadDistance(PolicyContract):
    """raw_units / 10**decimal_places metres, compared before any rounding.

    Up to six decimal places are numeric precision, not a GPS accuracy claim.
    Bounds are technical input bounds, not a commercial distance limit.
    """

    raw_units: Annotated[int, Field(strict=True, ge=0, le=10**15)]
    decimal_places: Annotated[int, Field(strict=True, ge=0, le=6)]
    unit: Literal["metre"] = "metre"


class ProvenanceFields(PolicyContract):
    evidence_ref: Identifier
    evidence_digest: Digest
    resolver_id: Identifier
    resolver_version: Identifier
    method_id: Identifier
    observed_at: datetime
    resolved_at: datetime


class InternalResolvedProvenance(ProvenanceFields):
    kind: Literal["internal_resolved"]


class SyntheticProvenance(ProvenanceFields):
    kind: Literal["synthetic_fixture"]
    fixture_suite: Identifier


Provenance = Annotated[
    InternalResolvedProvenance | SyntheticProvenance, Field(discriminator="kind")
]


class OrderBinding(PolicyContract):
    order_id: Identifier
    restaurant_id: Identifier
    driver_id: Identifier
    assignment_id: Identifier


class LocationIdentity(PolicyContract):
    location_id: Identifier
    location_digest: Digest


class EvidenceReference(PolicyContract):
    """An immutable reference identifies one document digest within an assessment."""

    evidence_ref: Identifier
    evidence_digest: Digest


class PolicyContext(PolicyContract):
    binding: OrderBinding
    assigned_at: datetime
    as_of: datetime
    # Selection is explicit and may be unavailable without blocking thresholds.
    # This policy never chooses a version or invents a missing-version token.
    tariff_version: Identifier | None = None
    evidence_mode: Literal["internal_resolved", "synthetic_fixture"]


class Zone1Mapping(PolicyContract):
    restaurant_id: Identifier
    tariff_version: Identifier
    zone1_id: Identifier
    provenance: Provenance | None = None


class Zone1CourierBasis(PolicyContract):
    restaurant_id: Identifier
    tariff_version: Identifier
    zone1_id: Identifier
    basis_kind: Literal["courier_remuneration"]
    currency: Literal["RON"]
    courier_remuneration_bani: MoneyBani
    provenance: Provenance | None = None


class DepartureFact(PolicyContract):
    binding: OrderBinding
    departure_id: Identifier
    origin: LocationIdentity
    departed_at: datetime
    provenance: Provenance | None = None


class DepartureRestaurantRoute(PolicyContract):
    binding: OrderBinding
    departure_id: Identifier
    route_id: Identifier
    route_digest: Digest
    origin: LocationIdentity
    restaurant_location: LocationIdentity
    measurement_kind: Literal["departure_to_restaurant_road_route"]
    total: RawRoadDistance | None = None
    provenance: Provenance | None = None


class TravelledRoadProgress(PolicyContract):
    binding: OrderBinding
    cancellation_id: Identifier
    departure_id: Identifier
    route_id: Identifier
    route_digest: Digest
    measurement_kind: Literal["actual_eligible_road_progress"]
    measured_until: datetime
    travelled: RawRoadDistance | None = None
    provenance: Provenance | None = None


class CancellationEvidence(PolicyContract):
    departure: DepartureFact | None = None
    route: DepartureRestaurantRoute | None = None
    progress: TravelledRoadProgress | None = None


class CancellationPolicyInput(PolicyContract):
    context: PolicyContext
    cancellation_id: Identifier
    cancelled_at: datetime
    state_before: Literal["ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]
    picked_up_at: datetime | None = None
    restaurant_location: LocationIdentity
    evidence: CancellationEvidence | None = None
    zone1_mapping: Zone1Mapping | None = None
    courier_basis: Zone1CourierBasis | None = None


class OriginalArrivalFact(PolicyContract):
    binding: OrderBinding
    arrival_id: Identifier
    original_address: LocationIdentity
    arrived_at: datetime
    # The resolver's authority to establish this fact is outside L5C1.
    fact_kind: Literal["original_destination_arrival"]
    provenance: Provenance | None = None


class PriorAddressChange(PolicyContract):
    """An internally resolved admitted change, regardless of its monetary result.

    This is not an admission generated by the evaluator. Even a prior zero or
    unpriced change consumes a slot. There is no arrival-at-new1 requirement.
    """

    binding: OrderBinding
    change_id: Identifier
    change_ordinal: Ordinal
    original_address: LocationIdentity
    source_address: LocationIdentity
    target_address: LocationIdentity
    original_arrival_id: Identifier
    original_arrival_digest: Digest
    changed_at: datetime
    provenance: Provenance | None = None


class DirectedAddressRoadSegment(PolicyContract):
    binding: OrderBinding
    change_id: Identifier
    source_address: LocationIdentity
    target_address: LocationIdentity
    measurement_kind: Literal["directed_address_road_segment"]
    distance: RawRoadDistance | None = None
    provenance: Provenance | None = None


class AddressChangePolicyInput(PolicyContract):
    context: PolicyContext
    change_id: Identifier
    change_ordinal: Ordinal
    changed_at: datetime
    picked_up_at: datetime
    state: Literal["PICKED_UP", "ACCEPTED", "DELIVERED", "CANCELLED"]
    original_address: LocationIdentity
    current_address: LocationIdentity
    target_address: LocationIdentity
    original_arrival: OriginalArrivalFact | None = None
    predecessor_id: Identifier | None = None
    history: Annotated[tuple[PriorAddressChange, ...], Field(max_length=2)] = ()
    segment: DirectedAddressRoadSegment | None = None
    zone1_mapping: Zone1Mapping | None = None
    courier_basis: Zone1CourierBasis | None = None


class ExceptionPolicyResult(PolicyContract):
    rule_version: Literal["L5C1-2026-10-14-v1"] = "L5C1-2026-10-14-v1"
    operation: Literal["pre_pickup_cancellation", "post_arrival_address_change"]
    evaluation_kind: Literal["policy_only"] = "policy_only"
    evidence_mode: Literal["internal_resolved", "synthetic_fixture"]
    eligibility: Literal["eligible", "zero", "unavailable"]
    courier_amount_bani: MoneyBani | None
    restaurant_bears_courier_compensation: bool | None
    restaurant_transport_surcharge_bani: None = None
    restaurant_transport_status: Literal["not_applicable", "unavailable"]
    pricing_status: Literal["complete", "partial", "unavailable"]
    reason_codes: Annotated[tuple[Identifier, ...], Field(max_length=40)]
    evidence_refs: Annotated[tuple[EvidenceReference, ...], Field(max_length=10)]
    courier_basis: Zone1CourierBasis | None = None
    # An assessment never asserts a transfer or changes the original quote.
    advance_paid_bani: None = None
    refund_due_bani: None = None
    refund_paid_bani: None = None
