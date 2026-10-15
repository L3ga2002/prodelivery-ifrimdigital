"""Strict full-products custody commands; monetary actions are not admitted."""
import uuid
from typing import Literal
from pydantic import field_validator, model_validator, model_serializer
from models.order_mutation import VersionedCommand

ROLES = {"delivery_wait_started": "driver", "delivery_failure_reviewed": "admin",
    "products_disposition_decided": "restaurant", "products_return_received": "restaurant",
    "products_keep_acknowledged": "driver"}
FIELDS = {"delivery_wait_started": {"reason"},
    "delivery_failure_reviewed": {"predecessor_id", "customer_contact_attempted", "restaurant_contacted", "coordination_confirmed"},
    "products_disposition_decided": {"predecessor_id", "decision"},
    "products_return_received": {"predecessor_id"}, "products_keep_acknowledged": {"predecessor_id"}}

class CustodyCommand(VersionedCommand):
    event_type: Literal["delivery_wait_started", "delivery_failure_reviewed", "products_disposition_decided", "products_return_received", "products_keep_acknowledged"]
    incident_id: str
    reason: Literal["absent", "refused"] | None = None
    predecessor_id: str | None = None
    decision: Literal["return", "keep"] | None = None
    customer_contact_attempted: bool | None = None
    restaurant_contacted: bool | None = None
    coordination_confirmed: bool | None = None

    @field_validator("client_operation_id", "incident_id", "predecessor_id")
    @classmethod
    def canonical(cls, value, info):
        if value is not None:
            parsed = uuid.UUID(value)
            if str(parsed) != value or info.field_name == "client_operation_id" and parsed.version != 4:
                raise ValueError("Canonical UUID required")
        return value

    @model_validator(mode="after")
    def shape(self):
        common = {"client_operation_id", "expected_order_version", "event_type", "incident_id"}
        if self.model_fields_set != common | FIELDS[self.event_type]:
            raise ValueError("Only the exact command fields are accepted")
        if any(getattr(self, name) is None for name in FIELDS[self.event_type]):
            raise ValueError("Command facts must be explicit")
        if self.event_type == "delivery_failure_reviewed" and not all(getattr(self, n) is True for n in (
            "customer_contact_attempted", "restaurant_contacted", "coordination_confirmed")):
            raise ValueError("Explicit coordination and contact facts required")
        return self

    @model_serializer(mode="wrap")
    def supplied(self, handler):
        return {k: v for k, v in handler(self).items() if k in self.model_fields_set}
