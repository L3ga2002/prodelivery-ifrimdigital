"""Additive contracts for versioned order operations; no persistence or auth."""

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal

from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator,
)

from models.order import OrderCreate, OrderItem
from models.order_finance import FinancialCreateRequest


OperationType = Literal["create", "edit", "assign", "preparing", "ready", "status"]
MAX_ORDER_VERSION = 9223372036854775807


class StrictOrderItem(OrderItem):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name_before_bounds(cls, value):
        return value.strip() if isinstance(value, str) else value


class StrictOrderCreate(OrderCreate):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    items: list[StrictOrderItem] = Field(default_factory=list, max_length=200)
    linked_problem_order_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("*", mode="before")
    @classmethod
    def trim_before_bounds(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_coordinate_pair(self):
        if (self.customer_latitude is None) != (self.customer_longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        return self


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class OrderCorrections(StrictContract):
    customer_name: str | None = Field(default=None, min_length=2, max_length=140)
    customer_phone: str | None = Field(default=None, min_length=7, max_length=24)
    customer_address: str | None = Field(default=None, min_length=5, max_length=300)
    customer_latitude: float | None = Field(default=None, ge=-90, le=90)
    customer_longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("*", mode="before")
    @classmethod
    def trim_before_bounds(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_nonempty_safe_patch(self):
        fields = self.model_fields_set
        if not fields:
            raise ValueError("At least one correction is required")
        for name in ("customer_name", "customer_phone", "customer_address"):
            if name in fields and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        coordinates = {"customer_latitude", "customer_longitude"}
        if fields & coordinates and not coordinates <= fields:
            raise ValueError("Coordinate corrections require both fields")
        if (self.customer_latitude is None) != (self.customer_longitude is None):
            raise ValueError("Coordinates must both be values or both be null")
        return self

    @model_serializer(mode="wrap")
    def serialize_present_corrections(self, handler):
        # Persist/replay must not turn omitted fields into explicit clearing.
        return {
            name: value for name, value in handler(self).items()
            if name in self.model_fields_set
        }


class OperationCommand(StrictContract):
    client_operation_id: str = Field(
        min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )


class VersionedCommand(OperationCommand):
    expected_order_version: int = Field(ge=0, le=MAX_ORDER_VERSION)


class QuoteConfirmation(StrictContract):
    contract_version: Literal[1]
    quote_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)

    @field_validator("contract_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Invalid confirmation version")
        return value


class CloseFinancialCreation(StrictContract):
    restaurant_id: str = Field(min_length=1, max_length=120)
    quote_confirmation: QuoteConfirmation

    @field_validator("restaurant_id")
    @classmethod
    def restaurant_identity(cls, value):
        return _trusted_identifier(value, "restaurant")


class FinancialCreationTerminal(CloseFinancialCreation):
    """A closed identity, never a financial command with a missing snapshot."""
    creation_terminal_contract_version: Literal[1]
    terminal_kind: Literal["financial_create_not_admitted"]
    key: str = Field(alias="_id")
    actor_id: str
    actor_role: Literal["admin"]
    client_operation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    state: Literal["rejected"]
    error_code: Literal["FINANCIAL_INTENT_CLOSED", "FINANCIAL_QUOTE_CHANGED"]
    error_status: Literal[409]
    created_at: str
    resolved_at: str

    @field_validator("creation_terminal_contract_version", "error_status", mode="before")
    @classmethod
    def exact_integer(cls, value):
        if type(value) is not int:
            raise ValueError("Invalid terminal integer")
        return value


class CreateOrderCommand(OperationCommand):
    order: StrictOrderCreate
    financial: FinancialCreateRequest | None = None
    quote_confirmation: QuoteConfirmation | None = None

    @model_validator(mode="after")
    def financial_presence(self):
        if "financial" in self.model_fields_set and self.financial is None:
            raise ValueError("An explicit financial request cannot be null")
        if "quote_confirmation" in self.model_fields_set and self.quote_confirmation is None:
            raise ValueError("An explicit confirmation cannot be null")
        if self.quote_confirmation is not None and (self.financial is None or self.financial.basis != "zone"):
            raise ValueError("Confirmation requires a zone financial request")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_intent(self, handler):
        data = handler(self)
        if self.financial is None:
            data.pop("financial", None)
        if self.quote_confirmation is None:
            data.pop("quote_confirmation", None)
        return data


class EditOrderCommand(VersionedCommand):
    changes: OrderCorrections


class AssignOrderCommand(VersionedCommand):
    driver_id: str = Field(min_length=1, max_length=120)

    @field_validator("driver_id")
    @classmethod
    def reject_blank_driver(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("Driver identifier must be nonblank and unpadded")
        return value


class PreparationCommand(VersionedCommand):
    preparation_time: int = Field(ge=1, le=240)


class ReadyOrderCommand(VersionedCommand):
    pass


class StatusOrderCommand(VersionedCommand):
    status: Literal["ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]
    cancellation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("cancellation_reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_cancellation(self):
        if self.status == "CANCELLED" and not self.cancellation_reason:
            raise ValueError("Cancellation requires a reason")
        if self.status != "CANCELLED" and self.cancellation_reason is not None:
            raise ValueError("Cancellation reason is only valid for cancellation")
        return self


COMMAND_TYPES = {
    "create": CreateOrderCommand,
    "edit": EditOrderCommand,
    "assign": AssignOrderCommand,
    "preparing": PreparationCommand,
    "ready": ReadyOrderCommand,
    "status": StatusOrderCommand,
}


@dataclass(frozen=True)
class MutationIntent:
    identity: tuple[str, OperationType, str]
    payload_digest: str


class MutationIntentConflict(ValueError):
    """An operation identity cannot be reused for a different intent."""


def _trusted_identifier(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 120:
        raise ValueError(f"Invalid {name}")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"Invalid {name}")
    return value


def _canonical_payload(value):
    if isinstance(value, float) and value == 0:
        return 0.0
    if isinstance(value, dict):
        return {key: _canonical_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_payload(item) for item in value]
    return value


def build_mutation_intent(authenticated_actor_id, operation_type, target_order_id, command):
    """The caller must authorize the actor and target; this only binds intent."""
    actor = _trusted_identifier(authenticated_actor_id, "authenticated actor")
    expected_class = COMMAND_TYPES.get(operation_type) if isinstance(operation_type, str) else None
    if expected_class is None or type(command) is not expected_class:
        raise ValueError("Command does not match operation type")
    # Revalidate constructed/mutated instances before trusting their fingerprint.
    command = expected_class.model_validate(command.model_dump(mode="python", exclude_unset=True))
    if operation_type == "create":
        if target_order_id is not None:
            raise ValueError("Creation does not accept a target order")
    else:
        target_order_id = _trusted_identifier(target_order_id, "target order")
    payload = command.model_dump(mode="json", exclude={"client_operation_id"})
    if isinstance(command, EditOrderCommand):
        # Unset correction fields are not the same intent as explicit clearing.
        payload["changes"] = command.changes.model_dump(mode="json", exclude_unset=True)
    canonical = json.dumps(
        {"contract_version": 1, "type": operation_type, "target": target_order_id,
         "payload": _canonical_payload(payload)},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return MutationIntent(
        identity=(actor, operation_type, command.client_operation_id),
        payload_digest=sha256(canonical.encode("utf-8")).hexdigest(),
    )


def compare_mutation_intent(existing: MutationIntent, candidate: MutationIntent) -> bool:
    if existing.identity != candidate.identity or existing.payload_digest != candidate.payload_digest:
        raise MutationIntentConflict("Operation identity or immutable intent does not match")
    return True


class MutationResult(OperationCommand):
    state: Literal["applied", "replayed", "pending", "rejected"]
    order_id: str | None = Field(default=None, min_length=1, max_length=120)
    order_version: int | None = Field(default=None, ge=0, le=MAX_ORDER_VERSION)
    error_code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    retry_after_seconds: int | None = Field(default=None, ge=1, le=60)

    @field_validator("order_id")
    @classmethod
    def validate_order_id(cls, value):
        return _trusted_identifier(value, "order") if value is not None else value

    @model_validator(mode="after")
    def enforce_outcome(self):
        if self.state in ("applied", "replayed"):
            if self.order_id is None or self.order_version is None:
                raise ValueError("Committed outcome requires order identity and version")
            if self.error_code is not None or self.retry_after_seconds is not None:
                raise ValueError("Committed outcome cannot carry an error or retry")
        else:
            if self.order_id is not None or self.order_version is not None:
                raise ValueError("Uncommitted outcome cannot claim an order result")
            if self.state == "pending":
                if self.retry_after_seconds is None or self.error_code is not None:
                    raise ValueError("Pending outcome requires retry delay and no error")
            elif self.error_code is None or self.retry_after_seconds is not None:
                raise ValueError("Rejected outcome requires error and no retry")
        return self
