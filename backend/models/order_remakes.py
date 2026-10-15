"""Explicit receipt decisions for the bounded financial remake protocol."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from models.order_finance import FinancialCreateRequest, MoneyBani
from models.order_mutation import MutationResult, QuoteConfirmation, StrictContract, VersionedCommand


class RemakeItem(StrictContract):
    name: str = Field(min_length=1, max_length=140)
    quantity: int = Field(ge=1, le=100)
    unit_price_bani: int = Field(strict=True, ge=0, le=10_000_000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class RemakeCommand(VersionedCommand):
    problem_type: Literal["missing_product", "new_product"]
    description: str = Field(min_length=3, max_length=1000)
    items: list[RemakeItem] = Field(min_length=1, max_length=200)
    # These decisions belong to this new receipt, never the original payment.
    payment_type: Literal["CASH", "CARD"]
    collection_basis: Literal["new_receipt", "prepaid_new_order"]
    client_collection_bani: MoneyBani
    advance_required_bani: MoneyBani
    financial: FinancialCreateRequest
    quote_confirmation: QuoteConfirmation | None = None

    @model_validator(mode="after")
    def confirmation_presence(self):
        if "quote_confirmation" in self.model_fields_set and self.quote_confirmation is None:
            raise ValueError("An explicit confirmation cannot be null")
        if self.quote_confirmation is not None and self.financial.basis != "zone":
            raise ValueError("Confirmation requires a zone financial request")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_intent(self, handler):
        data = handler(self)
        if self.quote_confirmation is None:
            data.pop("quote_confirmation", None)
        return data

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value):
        return value.strip() if isinstance(value, str) else value


class RemakeResult(MutationResult):
    parent_order_id: str | None = Field(default=None, min_length=1, max_length=120)
    parent_order_version: int | None = Field(default=None, ge=0, le=9223372036854775807)

    @model_validator(mode="after")
    def require_linked_receipt(self):
        if self.state in ("applied", "replayed"):
            if self.parent_order_id is None or self.parent_order_version is None or self.parent_order_id == self.order_id:
                raise ValueError("A remake receipt requires two distinct order identities")
        elif self.parent_order_id is not None or self.parent_order_version is not None:
            raise ValueError("An unresolved remake cannot claim a parent update")
        return self


Identifier = Annotated[str, Field(min_length=1, max_length=120)]
Revision = Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
OrderStatus = Literal["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]


class RemakePublicContract(StrictContract):
    @field_validator("contract_version", mode="before", check_fields=False)
    @classmethod
    def exact_public_version(cls, value):
        if type(value) is not int:
            raise ValueError("Invalid public version")
        return value

    @model_validator(mode="after")
    def safe_public_strings(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str) and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError("Invalid public field")
        return self


class CloseFinancialRemake(RemakePublicContract):
    restaurant_id: Identifier
    expected_order_version: Revision
    quote_confirmation: QuoteConfirmation

    @field_validator("restaurant_id")
    @classmethod
    def clean_identity(cls, value):
        if value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid identity")
        return value


class FinancialRemakeTerminal(CloseFinancialRemake):
    key: str = Field(alias="_id")
    remake_terminal_contract_version: Literal[1]
    terminal_kind: Literal["financial_remake_not_admitted"]
    actor_id: Identifier
    actor_role: Literal["admin", "restaurant"]
    target_order_id: Identifier
    client_operation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    state: Literal["rejected"]
    error_code: Literal["FINANCIAL_INTENT_CLOSED", "FINANCIAL_QUOTE_CHANGED"]
    error_status: Literal[409]
    created_at: str = Field(min_length=20, max_length=40)
    resolved_at: str = Field(min_length=20, max_length=40)

    @field_validator("remake_terminal_contract_version", "error_status", mode="before")
    @classmethod
    def exact_integer(cls, value):
        if type(value) is not int:
            raise ValueError("Invalid terminal integer")
        return value


class RemakeParent(RemakePublicContract):
    order_id: Identifier
    order_version: Revision
    status: OrderStatus
    source: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    customer_name: str = Field(min_length=2, max_length=140)
    customer_phone: str = Field(min_length=7, max_length=24)
    customer_address: str = Field(min_length=5, max_length=300)
    customer_latitude: float | None = Field(ge=-90, le=90)
    customer_longitude: float | None = Field(ge=-180, le=180)
    has_problem_followup: bool
    problem_followup_order_id: Identifier | None
    delivery_zone_id: Identifier | None
    delivery_zone_name: str | None = Field(min_length=1, max_length=160)
    delivery_sector: str | None = Field(max_length=80)
    delivery_zone_level: int | None = Field(strict=True, ge=0, le=50)

    @model_validator(mode="after")
    def coherent_fields(self):
        if (self.customer_latitude is None) != (self.customer_longitude is None):
            raise ValueError("Coordinates require a pair")
        for value in (self.order_id, self.customer_name, self.customer_phone, self.customer_address,
                self.problem_followup_order_id, self.delivery_zone_id, self.delivery_zone_name, self.delivery_sector):
            if value is not None and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError("Invalid parent field")
        if self.has_problem_followup != (self.problem_followup_order_id is not None):
            raise ValueError("Invalid followup marker")
        return self


class RemakeEligibility(RemakePublicContract):
    can_preview: bool
    blocking_code: Literal["REMAKE_REQUIRES_DELIVERED", "REMAKE_ALREADY_EXISTS", "ORDER_VERSION_EXHAUSTED",
        "RESTAURANT_PAUSED", "RESTAURANT_UNAVAILABLE", "FINANCIAL_REMAKE_NOT_ENABLED"] | None

    @model_validator(mode="after")
    def coherent_eligibility(self):
        if self.can_preview != (self.blocking_code is None):
            raise ValueError("Invalid eligibility")
        return self


class RemakeParentContext(RemakePublicContract):
    contract_version: Literal[1]
    kind: Literal["remake_parent"]
    actor_id: Identifier
    actor_role: Literal["admin", "restaurant"]
    restaurant_id: Identifier
    parent: RemakeParent
    eligibility: RemakeEligibility


class RemakeReadbackParent(RemakePublicContract):
    order_id: Identifier
    order_version: Revision
    status: OrderStatus
    has_problem_followup: Literal[True]
    problem_followup_order_id: Identifier

    @field_validator("has_problem_followup", mode="before")
    @classmethod
    def exact_followup(cls, value):
        if type(value) is not bool:
            raise ValueError("Invalid followup")
        return value


class RemakeReadbackChild(RemakePublicContract):
    order_id: Identifier
    order_version: Revision
    status: OrderStatus
    linked_problem_order_id: Identifier
    creation_kind: Literal["remake"]
    source: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    payment_type: Literal["CASH", "CARD"]


class RemakePublicFinancial(RemakePublicContract):
    contract_version: Literal[1]
    currency: Literal["RON"]
    tariff_version: Identifier
    products_bani: MoneyBani
    collection_mode: Literal["cash", "prepaid"]
    client_collection_bani: MoneyBani
    restaurant_transport_bani: MoneyBani
    advance_required_bani: MoneyBani
    advance_paid_bani: None
    refund_due_bani: None
    refund_paid_bani: None
    basis: Literal["zone"]
    zone_id: Identifier
    zone_name: str = Field(min_length=1, max_length=160)
    zone_sector: str | None = Field(max_length=80)
    zone_level: int | None = Field(strict=True, ge=0, le=50)


class RemakeReadback(RemakePublicContract):
    contract_version: Literal[1]
    kind: Literal["remake_readback"]
    actor_id: Identifier
    actor_role: Literal["admin", "restaurant"]
    restaurant_id: Identifier
    client_operation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    quote_confirmation: QuoteConfirmation
    receipt: RemakeResult
    parent: RemakeReadbackParent
    child: RemakeReadbackChild
    financial: RemakePublicFinancial
