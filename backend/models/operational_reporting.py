"""Strict operational reports; no financial resolution or implicit legacy migration."""
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class OperationalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    client_operation_id: str

    @field_validator("client_operation_id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError("Canonical UUID required")
        return value

class CloseDayCommand(OperationalCommand):
    pass

class IncidentCommand(OperationalCommand):
    expected_order_version: int | None = Field(ge=0, le=9223372036854775807)
    incident_type: Literal["missing_product", "damaged_product", "pickup_blocked", "delivery_blocked", "other"]
    description: str = Field(min_length=1, max_length=500)

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value):
        return value.strip() if isinstance(value, str) else value
