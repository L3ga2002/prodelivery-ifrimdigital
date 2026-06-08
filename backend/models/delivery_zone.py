from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone
import uuid


class ZoneCoordinate(BaseModel):
    lat: float
    lng: float


class DeliveryZone(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    restaurant_id: str
    restaurant_name: Optional[str] = None
    sector: str = "General"
    zone_level: int = 1
    name: str
    color: str = "#3388ff"
    fee: float = 5.0
    polygon: List[ZoneCoordinate] = []
    is_active: bool = True
    sort_order: int = 0
    is_locked: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeliveryZoneCreate(BaseModel):
    restaurant_id: str
    restaurant_name: Optional[str] = None
    sector: str = "General"
    zone_level: int = 1
    name: str
    color: str = "#3388ff"
    fee: float = 5.0
    polygon: List[ZoneCoordinate] = []
    is_active: bool = True
    sort_order: int = 0
    is_locked: bool = True


class DeliveryZoneUpdate(BaseModel):
    restaurant_id: Optional[str] = None
    restaurant_name: Optional[str] = None
    sector: Optional[str] = None
    zone_level: Optional[int] = None
    name: Optional[str] = None
    color: Optional[str] = None
    fee: Optional[float] = None
    polygon: Optional[List[ZoneCoordinate]] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    is_locked: Optional[bool] = None
    confirm_protected_action: bool = False


class ZoneDetectRequest(BaseModel):
    restaurant_id: Optional[str] = None
    lat: float
    lng: float
