"""L4A declaration and restaurant approval; actual payments are not enabled."""
from typing import Literal
import uuid
from pydantic import Field, field_validator, model_validator
from models.order_mutation import VersionedCommand


class FinancialEventCommand(VersionedCommand):
    event_type: Literal["advance_not_paid_declared", "advance_shortfall_acknowledged"]
    amount_bani: int = Field(gt=0, le=100_000_000)
    declaration_id: str | None

    @field_validator("declaration_id")
    @classmethod
    def canonical_declaration(cls, value):
        if value is not None and str(uuid.UUID(value)) != value:
            raise ValueError("A canonical declaration identity is required")
        return value

    @model_validator(mode="after")
    def event_link(self):
        if ((self.event_type == "advance_not_paid_declared") != (self.declaration_id is None)):
            raise ValueError("Approval requires the exact declaration; declaration cannot link another declaration")
        return self
