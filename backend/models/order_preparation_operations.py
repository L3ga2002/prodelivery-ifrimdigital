"""Strict, additive preparation intents and immutable preparation receipts."""

from datetime import datetime
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from models.order_mutation import OperationCommand
from utils.order_revision import MAX_ORDER_VERSION


class PreparationOperationCommand(OperationCommand):
    # Required even for legacy orders: null means that the field was absent.
    expected_order_version: int | None = Field(ge=0, le=MAX_ORDER_VERSION)


class PreparingOperationCommand(PreparationOperationCommand):
    preparation_time: int = Field(ge=1, le=240)


class ReadyOperationCommand(PreparationOperationCommand):
    pass


COMMAND_TYPES = {"preparing": PreparingOperationCommand, "ready": ReadyOperationCommand}
RECEIPT_FIELDS = (
    "order_id", "order_version", "preparation_status", "preparation_time",
    "preparation_started_at", "preparation_due_at", "preparation_ready_at",
    "preparation_estimated_seconds", "preparation_actual_seconds", "preparation_delay_seconds",
)


def preparation_digest(operation_type, order_id, command):
    expected = COMMAND_TYPES.get(operation_type)
    if expected is None or type(command) is not expected:
        raise ValueError("Command does not match preparation operation")
    command = expected.model_validate(command.model_dump(mode="python", exclude_unset=True))
    if (not isinstance(order_id, str) or not 1 <= len(order_id) <= 120
        or order_id != order_id.strip() or any(ord(c) < 32 or ord(c) == 127 for c in order_id)):
        raise ValueError("Invalid target identity")
    return digest({"contract_version": 1, "type": operation_type, "target": order_id,
                   "payload": command.model_dump(mode="json", exclude={"client_operation_id"})})


def digest(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


class PreparationResult(OperationCommand):
    state: Literal["applied", "replayed", "pending", "rejected"]
    order_id: str | None = Field(default=None, min_length=1, max_length=120)
    order_version: int | None = Field(default=None, ge=0, le=MAX_ORDER_VERSION)
    preparation_status: Literal["PREPARING", "READY"] | None = None
    preparation_time: int | None = Field(default=None, ge=1, le=240)
    preparation_started_at: str | None = None
    preparation_due_at: str | None = None
    preparation_ready_at: str | None = None
    preparation_estimated_seconds: int | None = Field(default=None, ge=0, le=240 * 60)
    preparation_actual_seconds: int | None = Field(default=None, ge=0, le=MAX_ORDER_VERSION)
    preparation_delay_seconds: int | None = Field(default=None, ge=0, le=MAX_ORDER_VERSION)
    error_code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    retry_after_seconds: int | None = Field(default=None, ge=1, le=60)

    @field_validator("order_id")
    @classmethod
    def valid_order_id(cls, value):
        if value is not None and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Invalid order identity")
        return value

    @field_validator("preparation_started_at", "preparation_due_at", "preparation_ready_at")
    @classmethod
    def canonical_utc_timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0 or parsed.isoformat() != value:
                raise ValueError("Receipt timestamps require canonical UTC")
        return value

    @model_validator(mode="after")
    def consistent_result(self):
        if self.state in {"applied", "replayed"}:
            if self.order_id is None or self.preparation_status is None:
                raise ValueError("Committed receipt requires order and preparation identities")
            if self.error_code is not None or self.retry_after_seconds is not None:
                raise ValueError("Committed receipt cannot carry error or retry")
            if self.preparation_status == "PREPARING" and any(value is None for value in (
                self.preparation_time, self.preparation_started_at, self.preparation_due_at,
                self.preparation_estimated_seconds,
            )):
                raise ValueError("Preparing receipt requires the original schedule")
            if self.preparation_status == "PREPARING":
                duration = (datetime.fromisoformat(self.preparation_due_at)
                            - datetime.fromisoformat(self.preparation_started_at)).total_seconds()
                if (self.preparation_estimated_seconds != self.preparation_time * 60
                    or duration != self.preparation_estimated_seconds):
                    raise ValueError("Preparing receipt schedule does not match the original duration")
            if self.preparation_status == "READY" and (self.preparation_ready_at is None
                                                       or self.preparation_delay_seconds is None):
                raise ValueError("Ready receipt requires the original completion")
            if self.preparation_status == "READY":
                if self.preparation_started_at is None:
                    if self.preparation_actual_seconds is not None or self.preparation_delay_seconds != 0:
                        raise ValueError("Legacy completion without a start cannot claim an elapsed time")
                else:
                    actual = max(int((datetime.fromisoformat(self.preparation_ready_at)
                                      - datetime.fromisoformat(self.preparation_started_at)).total_seconds()), 0)
                    estimate = (self.preparation_estimated_seconds if self.preparation_estimated_seconds is not None
                                else (self.preparation_time or 0) * 60)
                    if self.preparation_actual_seconds != actual or self.preparation_delay_seconds != max(actual - estimate, 0):
                        raise ValueError("Ready receipt elapsed time does not match the original timestamps")
        else:
            if any(getattr(self, field) is not None for field in RECEIPT_FIELDS):
                raise ValueError("Uncommitted response cannot claim an effect")
            if self.state == "pending":
                if self.retry_after_seconds is None or self.error_code is not None:
                    raise ValueError("Pending response requires retry only")
            elif self.error_code is None or self.retry_after_seconds is not None:
                raise ValueError("Rejected response requires error only")
        return self
