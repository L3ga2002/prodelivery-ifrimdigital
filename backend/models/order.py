from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, model_serializer
from typing import Literal, Optional
from datetime import datetime, timezone
import uuid
from models.order_finance import FinancialSnapshot
from models.financial_activity import FinancialActivity
from models.custody_activity import CustodyActivity


ORDER_STATUS_VALUES = ("NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED")
OrderStatus = Literal["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]
PaymentType = Literal["CASH", "CARD"]
ProblemType = Literal["missing_product", "new_product"]


def _strip_text(value: str) -> str:
    return value.strip()


def _strip_required_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Field cannot be empty")
    return stripped


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=140)
    quantity: int = Field(ge=1, le=100)
    price: float = Field(ge=0, le=100000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required_text(value)


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_number: str
    source: str = "S"
    restaurant_id: str
    restaurant_name: str
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    customer_name: str
    customer_phone: str
    customer_address: str
    customer_latitude: Optional[float] = None
    customer_longitude: Optional[float] = None
    items: list[OrderItem] = Field(default_factory=list)
    subtotal_amount: float = 0
    delivery_fee: float = 0
    total_amount: float
    payment_type: PaymentType
    order_version: int | None = Field(default=None, strict=True, ge=0, le=9223372036854775807)
    creation_operation_ref: str | None = None
    financial_contract_version: int | None = Field(default=None, strict=True, ge=1, le=1)
    financial: FinancialSnapshot | None = None
    financial_activity_contract_version: int | None = Field(default=None, strict=True, ge=1, le=1)
    financial_activity: FinancialActivity | None = None
    custody_contract_version: int | None = Field(default=None, strict=True, ge=1, le=1)
    custody_activity: CustodyActivity | None = None
    notes: Optional[str] = None
    status: OrderStatus = "NEW"
    zone: Optional[str] = None
    delivery_zone_id: Optional[str] = None
    delivery_zone_name: Optional[str] = None
    delivery_sector: Optional[str] = None
    delivery_zone_level: Optional[int] = None
    linked_problem_order_id: Optional[str] = None
    has_problem_followup: bool | None = Field(default=None, strict=True)
    problem_followup_order_id: str | None = Field(default=None, max_length=120)
    problem_followup_operation_ref: str | None = Field(default=None, max_length=128)
    remake_operation_ref: str | None = Field(default=None, max_length=128)
    problem_type: Optional[str] = None
    problem_description: Optional[str] = None
    preparation_time: Optional[int] = None
    preparation_status: Optional[Literal["NEW", "PREPARING", "READY"]] = None
    preparation_started_at: Optional[str] = None
    preparation_due_at: Optional[str] = None
    preparation_ready_at: Optional[str] = None
    preparation_estimated_seconds: Optional[int] = None
    preparation_actual_seconds: Optional[int] = None
    preparation_delay_seconds: Optional[int] = None
    assigned_at: Optional[str] = None
    accepted_at: Optional[str] = None
    picked_up_at: Optional[str] = None
    delivered_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancellation_reason: Optional[str] = None
    audit_trail: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def financial_markers_agree(self):
        if self.model_fields_set & {"custody_activity", "custody_contract_version"}:
            from utils.custody_activity import inspect_custody, CustodyError
            try:
                # Avoid calling the custom serializer while validation is in progress.
                value = {k: getattr(self, k) for k in self.model_fields_set}
                for k in ("custody_activity", "financial_activity", "financial"):
                    if value.get(k) is not None:
                        value[k] = value[k].model_dump(mode="json")
                if "items" in value:
                    value["items"] = [v.model_dump(mode="json") for v in value["items"]]
                inspect_custody(value)
            except CustodyError:
                raise ValueError("Custody requires its exact bound lifecycle") from None
        if self.model_fields_set & {"financial", "financial_contract_version"}:
            if (self.financial is None or self.financial_contract_version != 1
                    or self.order_version is None or self.creation_operation_ref != self.financial.operation_ref
                    or self.restaurant_id != self.financial.restaurant_id):
                raise ValueError("Financial orders require their complete versioned lineage")
        if self.model_fields_set & {"financial_activity", "financial_activity_contract_version"}:
            activity = self.financial_activity
            if (activity is None or self.financial_activity_contract_version != 1 or self.financial is None
                or activity.order_id != self.id or activity.restaurant_id != self.restaurant_id
                or activity.driver_id != self.driver_id or activity.financial_snapshot_digest != self.financial.snapshot_digest
                or activity.declared_unpaid_bani != self.financial.advance_required_bani
                or self.financial.collection_mode != "cash" or self.financial.advance_required_bani <= 0
                or activity.assigned_at != self.assigned_at or activity.accepted_at != self.accepted_at):
                raise ValueError("Financial activity requires the complete immutable quote and assignment binding")
            if ((activity.status == "outstanding" and (self.status not in {"PICKED_UP", "DELIVERED"} and not (self.status == "CANCELLED" and self.custody_activity is not None) or activity.picked_up_at != self.picked_up_at))
                or (activity.status != "outstanding" and (self.status not in {"ACCEPTED", "CANCELLED"} or self.picked_up_at is not None))):
                raise ValueError("Financial activity must agree with actual custody")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        data = handler(self)
        for name in ("order_version", "creation_operation_ref", "financial_contract_version", "financial",
                     "financial_activity_contract_version", "financial_activity", "custody_contract_version", "custody_activity",
                     "has_problem_followup", "problem_followup_order_id", "problem_followup_operation_ref", "remake_operation_ref"):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restaurant_id: str = Field(min_length=1, max_length=120)
    customer_name: str = Field(min_length=2, max_length=140)
    customer_phone: str = Field(min_length=7, max_length=24)
    customer_address: str = Field(min_length=5, max_length=300)
    customer_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    customer_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    items: list[OrderItem] = Field(default_factory=list, max_length=200)
    subtotal_amount: Optional[float] = Field(default=None, ge=0, le=1000000)
    delivery_fee: Optional[float] = Field(default=None, ge=0, le=1000000)
    total_amount: float = Field(ge=0, le=1000000)
    payment_type: PaymentType = "CASH"
    notes: Optional[str] = Field(default=None, max_length=1000)
    source: str = Field(default="S", min_length=1, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    delivery_zone_id: Optional[str] = Field(default=None, max_length=120)
    delivery_zone_name: Optional[str] = Field(default=None, max_length=160)
    delivery_sector: Optional[str] = Field(default=None, max_length=80)
    delivery_zone_level: Optional[int] = Field(default=None, ge=0, le=50)
    linked_problem_order_id: Optional[str] = None
    problem_type: Optional[ProblemType] = None
    problem_description: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("restaurant_id", "customer_name", "customer_phone", "customer_address", "source")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return _strip_required_text(value)

    @field_validator("notes", "delivery_zone_id", "delivery_zone_name", "delivery_sector", "linked_problem_order_id", "problem_description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return _strip_text(value) if value is not None else None

    @model_validator(mode="after")
    def ensure_problem_fields_are_consistent(self):
        if self.problem_type and not self.problem_description:
            raise ValueError("Problem description is required when problem_type is provided")
        return self


class AssignOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str = Field(min_length=1, max_length=120)

    @field_validator("driver_id")
    @classmethod
    def strip_driver_id(cls, value: str) -> str:
        return _strip_required_text(value)


class UpdateOrderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    cancellation_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("cancellation_reason")
    @classmethod
    def strip_cancellation_reason(cls, value: str | None) -> str | None:
        return _strip_text(value) if value is not None else None


class PreparationTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preparation_time: int = Field(ge=1, le=240)


class ProblemOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_type: ProblemType
    problem_description: str = Field(min_length=3, max_length=1000)
    item_name: Optional[str] = Field(default=None, max_length=140)
    quantity: int = Field(default=1, ge=1, le=100)
    price: float = Field(default=0, ge=0, le=100000)

    @field_validator("problem_description")
    @classmethod
    def strip_problem_description(cls, value: str) -> str:
        return _strip_required_text(value)

    @field_validator("item_name")
    @classmethod
    def strip_item_name(cls, value: str | None) -> str | None:
        return _strip_text(value) if value is not None else None
