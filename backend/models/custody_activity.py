"""Bounded private custody projection. Its public view contains no ledger bindings."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def activity_digest(value):
    return digest({k: v for k, v in value.items() if k != "activity_digest"})


class CustodyBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    order_id: str = Field(min_length=1, max_length=120)
    restaurant_id: str = Field(min_length=1, max_length=120)
    driver_id: str = Field(min_length=1, max_length=120)
    driver_user_id: str = Field(min_length=1, max_length=120)
    assigned_at: str = Field(max_length=64)
    accepted_at: str = Field(max_length=64)
    picked_up_at: str = Field(max_length=64)
    products_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    finance_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    incident_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("order_id", "restaurant_id", "driver_id", "driver_user_id")
    @classmethod
    def identifiers(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid bound identity")
        return value

    @model_validator(mode="after")
    def coherent(self):
        times = [datetime.fromisoformat(getattr(self, n)) for n in ("assigned_at", "accepted_at", "picked_up_at")]
        if any(t.tzinfo is None for t in times) or times != sorted(times):
            raise ValueError("Invalid custody chronology")
        return self


class CustodyActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    contract_version: Literal[1]
    status: Literal["waiting", "reviewed", "return_requested", "keep_authorized", "returned", "kept"]
    driver_id: str = Field(min_length=1, max_length=120)
    incident_id: str
    reason: Literal["absent", "refused"]
    arrival_evidence: Literal["declared"]
    wait_event_id: str
    wait_started_at: str
    wait_eligible_at: str
    review_id: str | None
    reviewed_at: str | None
    customer_contact_attempted: bool | None
    restaurant_contacted: bool | None
    coordination_confirmed: bool | None
    decision_id: str | None
    decision: Literal["return", "keep"] | None
    decided_at: str | None
    resolution_id: str | None
    resolved_at: str | None
    pricing_status: Literal["pending"]
    binding: CustodyBinding
    event_ids: list[str] = Field(min_length=1, max_length=4)
    activity_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("contract_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("Integer required")
        return value

    @field_validator("incident_id", "wait_event_id", "review_id", "decision_id", "resolution_id")
    @classmethod
    def ids(cls, value):
        if value is not None and str(uuid.UUID(value)) != value:
            raise ValueError("Canonical event id required")
        return value

    @field_validator("wait_started_at", "wait_eligible_at", "reviewed_at", "decided_at", "resolved_at")
    @classmethod
    def dates(cls, value):
        if value is not None and (not 1 <= len(value) <= 64 or datetime.fromisoformat(value).tzinfo is None):
            raise ValueError("Timezone-aware server time required")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if self.driver_id != self.binding.driver_id:
            raise ValueError("Custodian mismatch")
        wait = datetime.fromisoformat(self.wait_started_at)
        try:
            eligible = wait + timedelta(seconds=600)
        except OverflowError:
            raise ValueError("Wait timestamp is outside the supported range") from None
        if wait < datetime.fromisoformat(self.binding.picked_up_at) or datetime.fromisoformat(self.wait_eligible_at) != eligible:
            raise ValueError("Invalid declared wait")
        level = {"waiting": 1, "reviewed": 2, "return_requested": 3, "keep_authorized": 3, "returned": 4, "kept": 4}[self.status]
        ids = [self.wait_event_id, self.review_id, self.decision_id, self.resolution_id]
        dates = [self.wait_started_at, self.reviewed_at, self.decided_at, self.resolved_at]
        if (any(v is None for v in ids[:level] + dates[:level]) or any(v is not None for v in ids[level:] + dates[level:])
            or self.event_ids != ids[:level] or len(set(self.event_ids)) != level):
            raise ValueError("Exact event chain required")
        times = [datetime.fromisoformat(v) for v in dates[:level]]
        if times != sorted(times) or level > 1 and (times[1] - wait).total_seconds() < 600:
            raise ValueError("Incomplete wait or invalid chronology")
        facts = [self.customer_contact_attempted, self.restaurant_contacted, self.coordination_confirmed]
        if (level == 1 and any(v is not None for v in facts)) or (level > 1 and not all(v is True for v in facts)):
            raise ValueError("Explicit review facts required")
        if level < 3 and self.decision is not None or level >= 3 and self.decision != ("return" if self.status in {"return_requested", "returned"} else "keep"):
            raise ValueError("Decision mismatch")
        if self.activity_digest != activity_digest(self.model_dump(mode="json")):
            raise ValueError("Projection digest mismatch")
        return self

    def public(self):
        return self.model_dump(mode="json", exclude={"binding", "event_ids", "activity_digest"})
