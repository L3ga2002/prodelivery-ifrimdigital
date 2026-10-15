"""Public read models, separate from the immutable private admission snapshot."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from models.order_finance import FinanceContract, Identifier, MoneyBani


class PublicOrderFinancial(FinanceContract):
    contract_version: Literal[1]
    currency: Literal["RON"]
    restaurant_id: Identifier
    tariff_version: Identifier
    products_bani: MoneyBani
    collection_mode: Literal["cash", "prepaid"]
    client_collection_bani: MoneyBani
    restaurant_transport_bani: MoneyBani
    advance_required_bani: MoneyBani
    advance_paid_bani: None
    refund_due_bani: None
    refund_paid_bani: None
    basis: Literal["zone", "outside"]
    snapshot_at: Annotated[str, Field(min_length=20, max_length=40)]

    @field_validator("snapshot_at")
    @classmethod
    def utc_time(cls, value):
        when = datetime.fromisoformat(value)
        if when.tzinfo is None or when.utcoffset() != timezone.utc.utcoffset(when):
            raise ValueError("UTC snapshot timestamp required")
        return value

    @model_validator(mode="after")
    def obligations(self):
        collection = self.products_bani if self.collection_mode == "cash" else 0
        if self.client_collection_bani != collection or self.advance_required_bani != collection:
            raise ValueError("Inconsistent collection obligations")
        return self


class AssignedDriverOrderFinancial(PublicOrderFinancial):
    courier_remuneration_bani: MoneyBani


@dataclass(frozen=True)
class ReadContext:
    """Server-owned result of current-user authorization; never a request DTO."""
    actor_id: str
    role: str
    restaurant_id: str | None = None
    driver_id: str | None = None

    @property
    def scope(self):
        if self.role == "restaurant":
            return {"restaurant_id": self.restaurant_id}
        if self.role == "driver":
            return {"driver_id": self.driver_id}
        if self.role == "admin":
            return {}
        raise ValueError("Invalid read context")

    @property
    def visibility(self):
        return "assigned_driver" if self.role == "driver" else "restaurant"
