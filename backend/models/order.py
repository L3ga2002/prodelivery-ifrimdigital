from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone
import uuid


class OrderItem(BaseModel):
    name: str
    quantity: int
    price: float


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
    items: List[OrderItem] = []
    subtotal_amount: float = 0
    delivery_fee: float = 0
    total_amount: float
    payment_type: str
    notes: Optional[str] = None
    status: str = "NEW"
    zone: Optional[str] = None
    delivery_zone_id: Optional[str] = None
    delivery_zone_name: Optional[str] = None
    delivery_sector: Optional[str] = None
    delivery_zone_level: Optional[int] = None
    linked_problem_order_id: Optional[str] = None
    problem_type: Optional[str] = None
    problem_description: Optional[str] = None
    preparation_time: Optional[int] = None
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderCreate(BaseModel):
    restaurant_id: str
    customer_name: str
    customer_phone: str
    customer_address: str
    customer_latitude: Optional[float] = None
    customer_longitude: Optional[float] = None
    items: List[OrderItem] = []
    subtotal_amount: Optional[float] = None
    delivery_fee: Optional[float] = None
    total_amount: float
    payment_type: str = "CASH"
    notes: Optional[str] = None
    source: str = "S"
    linked_problem_order_id: Optional[str] = None
    problem_type: Optional[str] = None
    problem_description: Optional[str] = None


class AssignOrder(BaseModel):
    driver_id: str


class UpdateOrderStatus(BaseModel):
    status: str
    cancellation_reason: Optional[str] = None


class PreparationTime(BaseModel):
    preparation_time: int


class ProblemOrderCreate(BaseModel):
    problem_type: str
    problem_description: str
    item_name: Optional[str] = None
    quantity: int = 1
    price: float = 0
