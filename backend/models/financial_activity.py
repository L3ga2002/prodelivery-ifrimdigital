"""Strict bounded projection of declarations/approvals; never evidence of payment."""
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def activity_digest(value):
    return sha256(json.dumps({k: v for k, v in value.items() if k != "activity_digest"},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class FinancialActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    contract_version: Literal[1]
    status: Literal["declared", "approved", "outstanding"]
    driver_id: str = Field(min_length=1, max_length=120)
    declared_unpaid_bani: int = Field(gt=0, le=100_000_000)
    declaration_id: str
    approval_id: str | None
    declared_at: str
    approved_at: str | None
    picked_up_at: str | None
    outstanding_bani: int | None = Field(ge=1, le=100_000_000)
    repayment_due_policy: Literal["next_pickup_else_shift_end"] | None
    order_id: str = Field(min_length=1, max_length=120)
    restaurant_id: str = Field(min_length=1, max_length=120)
    assigned_at: str
    accepted_at: str
    financial_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    activity_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    pickup_event_id: str | None
    declaration_actor_id: str = Field(min_length=1, max_length=120)
    approval_actor_id: str | None = Field(min_length=1, max_length=120)
    pickup_actor_id: str | None = Field(min_length=1, max_length=120)

    @field_validator("contract_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("An integer contract version is required")
        return value

    @field_validator("driver_id", "order_id", "restaurant_id", "declaration_actor_id", "approval_actor_id", "pickup_actor_id")
    @classmethod
    def identifiers(cls, value):
        if value is not None and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Invalid identifier")
        return value

    @field_validator("declaration_id", "approval_id", "pickup_event_id")
    @classmethod
    def event_ids(cls, value):
        if value is not None and str(uuid.UUID(value)) != value:
            raise ValueError("A canonical event identity is required")
        return value

    @field_validator("declared_at", "approved_at", "picked_up_at", "assigned_at", "accepted_at")
    @classmethod
    def dates(cls, value):
        if value is not None:
            if not 1 <= len(value) <= 64 or datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("A bounded timezone-aware timestamp is required")
        return value

    @model_validator(mode="after")
    def coherent(self):
        declaration = datetime.fromisoformat(self.declared_at)
        accepted = datetime.fromisoformat(self.accepted_at)
        assigned = datetime.fromisoformat(self.assigned_at)
        if not assigned <= accepted <= declaration:
            raise ValueError("Invalid declaration chronology")
        if self.status == "declared":
            if self.approval_id is not None or self.approved_at is not None or self.approval_actor_id is not None:
                raise ValueError("Declaration is not approval")
        elif self.approval_id is None or self.approved_at is None or self.approval_actor_id is None:
            raise ValueError("Approval evidence is required")
        if self.approved_at is not None and datetime.fromisoformat(self.approved_at) < declaration:
            raise ValueError("Approval must follow declaration")
        if self.status == "outstanding":
            if (self.picked_up_at is None or self.outstanding_bani != self.declared_unpaid_bani
                or self.pickup_event_id is None
                or self.pickup_actor_id is None
                or self.repayment_due_policy != "next_pickup_else_shift_end"
                or datetime.fromisoformat(self.picked_up_at) < datetime.fromisoformat(self.approved_at)):
                raise ValueError("Outstanding debt requires an approved pickup")
        elif any(v is not None for v in (self.picked_up_at, self.outstanding_bani, self.repayment_due_policy, self.pickup_event_id, self.pickup_actor_id)):
            raise ValueError("A pre-pickup declaration is not outstanding debt")
        if self.activity_digest != activity_digest(self.model_dump(mode="json")):
            raise ValueError("Activity digest mismatch")
        return self

    def public(self):
        return {key: value for key, value in self.model_dump(mode="json").items() if key not in {
            "order_id", "restaurant_id", "assigned_at", "accepted_at", "financial_snapshot_digest", "activity_digest", "pickup_event_id",
            "declaration_actor_id", "approval_actor_id", "pickup_actor_id"}}
