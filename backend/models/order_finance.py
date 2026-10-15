"""Opt-in RON contracts. Integers are bani; null never means a zero payment."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_MONEY_BANI = 100_000_000
MAX_EARNED_BANI = 9_000_000_000_000_000
MoneyBani = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_BANI)]
Identifier = Annotated[str, Field(min_length=1, max_length=120)]


class FinanceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    @field_validator("contract_version", mode="before", check_fields=False)
    @classmethod
    def strict_contract_version(cls, value):
        if type(value) is not int:
            raise ValueError("Contract version must be an integer")
        return value

    @field_validator("*", mode="before")
    @classmethod
    def safe_strings(cls, value):
        if isinstance(value, str) and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Text must be unpadded and contain no control characters")
        return value


class FinancialCreateRequest(FinanceContract):
    contract_version: Literal[1] = 1
    tariff_version: Identifier
    products_bani: MoneyBani
    basis: Literal["zone", "outside"]
    zone_id: Identifier | None = None
    route_distance_m: Annotated[int, Field(strict=True, ge=0, le=10_000_000)] | None = None
    distance_evidence_ref: Identifier | None = None

    @model_validator(mode="after")
    def coherent_basis(self):
        if self.basis == "zone":
            if self.zone_id is None or self.route_distance_m is not None or self.distance_evidence_ref is not None:
                raise ValueError("A zone quote requires exactly a zone identifier")
        elif self.zone_id is not None or self.route_distance_m is None or self.distance_evidence_ref is None:
            raise ValueError("An outside quote requires an explicit road distance and evidence")
        return self


class ZoneTariff(FinanceContract):
    restaurant_transport_bani: MoneyBani | None = None
    courier_remuneration_bani: MoneyBani | None = None


class OutsideTariff(FinanceContract):
    # No global defaults: the approved restaurant/version provides every value.
    distance_rounding: Literal["floor_km"]
    restaurant_rate_per_km_bani: MoneyBani
    restaurant_minimum_bani: MoneyBani
    courier_remuneration_bani: MoneyBani | None = None


class RestaurantTariffVersion(FinanceContract):
    contract_version: Literal[1] = 1
    restaurant_id: Identifier
    version: Identifier
    currency: Literal["RON"]
    approved: bool
    zones: dict[Identifier, ZoneTariff] = Field(max_length=500)
    outside: OutsideTariff | None = None

    @field_validator("zones")
    @classmethod
    def safe_zone_identifiers(cls, value):
        for name in value:
            cls.safe_strings(name)
        return value


class SelectedTariffRule(FinanceContract):
    restaurant_transport_bani: MoneyBani
    courier_remuneration_bani: MoneyBani
    distance_rounding: Literal["floor_km"] | None = None
    restaurant_rate_per_km_bani: MoneyBani | None = None
    restaurant_minimum_bani: MoneyBani | None = None


class FinancialSnapshot(FinanceContract):
    contract_version: Literal[1]
    currency: Literal["RON"]
    restaurant_id: Identifier
    tariff_version: Identifier
    operation_ref: Annotated[str, Field(min_length=1, max_length=128)]
    snapshot_at: Annotated[str, Field(min_length=20, max_length=40)]
    snapshot_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    products_bani: MoneyBani
    collection_mode: Literal["cash", "prepaid"]
    client_collection_bani: MoneyBani
    restaurant_transport_bani: MoneyBani
    courier_remuneration_bani: MoneyBani
    advance_required_bani: MoneyBani
    # These are deliberately unknown in a creation quote. Actual transfer
    # evidence belongs to later, separately authorized financial operations.
    advance_paid_bani: None
    refund_due_bani: None
    refund_paid_bani: None
    basis: Literal["zone", "outside"]
    zone_id: Identifier | None
    zone_name: Annotated[str, Field(max_length=160)] | None
    zone_sector: Annotated[str, Field(max_length=80)] | None
    zone_level: Annotated[int, Field(strict=True, ge=0, le=50)] | None
    route_distance_m: Annotated[int, Field(strict=True, ge=0, le=10_000_000)] | None
    distance_evidence_ref: Identifier | None
    tariff_rule: SelectedTariffRule

    @model_validator(mode="after")
    def coherent_snapshot(self):
        expected_collection = self.products_bani if self.collection_mode == "cash" else 0
        if self.client_collection_bani != expected_collection or self.advance_required_bani != expected_collection:
            raise ValueError("Collection and advance obligations do not match the payment mode")
        if (self.tariff_rule.restaurant_transport_bani != self.restaurant_transport_bani
                or self.tariff_rule.courier_remuneration_bani != self.courier_remuneration_bani):
            raise ValueError("Amounts do not match the selected tariff rule")
        rule = self.tariff_rule
        if self.basis == "zone":
            if (self.zone_id is None or self.route_distance_m is not None or self.distance_evidence_ref is not None
                    or any(v is not None for v in (rule.distance_rounding, rule.restaurant_rate_per_km_bani, rule.restaurant_minimum_bani))):
                raise ValueError("Invalid zonal pricing evidence")
        elif (self.zone_id is not None or self.route_distance_m is None or self.distance_evidence_ref is None
                or any(v is not None for v in (self.zone_name, self.zone_sector, self.zone_level))
                or rule.distance_rounding != "floor_km" or rule.restaurant_rate_per_km_bani is None
                or rule.restaurant_minimum_bani is None
                or self.restaurant_transport_bani != max(rule.restaurant_minimum_bani,
                    self.route_distance_m // 1000 * rule.restaurant_rate_per_km_bani)):
            raise ValueError("Invalid outside pricing evidence")
        return self
