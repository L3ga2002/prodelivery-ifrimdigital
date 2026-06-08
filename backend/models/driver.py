from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Literal, Optional
from datetime import datetime, timezone
import uuid


DriverOperationalStatus = Literal["active", "delivery", "break", "offline"]


class Driver(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    phone: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[Literal["masculin", "feminin"]] = None
    cnp: Optional[str] = None
    phone_verified: bool = False
    vehicle_type: Literal["scooter", "car"] = "scooter"
    email_verified: bool = False
    is_active: bool = False
    driver_status: DriverOperationalStatus = "offline"
    break_started_at: Optional[str] = None
    break_until: Optional[str] = None
    active_avatar_id: Optional[str] = None
    avatar_url: Optional[str] = None
    latitude: float = 46.567
    longitude: float = 26.913
    current_order_id: Optional[str] = None
    total_deliveries: int = 0
    total_earnings: float = 0
    punctuality_rate: float = 0.85
    manual_ranking_score: Optional[float] = None
    manual_rank_note: Optional[str] = None
    manual_rank_updated_at: Optional[str] = None
    manual_rank_updated_by: Optional[str] = None
    joined_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DriverCreate(BaseModel):
    name: str
    phone: str
    email: EmailStr
    vehicle_type: Literal["scooter", "car"] = "scooter"


class DriverEmailVerification(BaseModel):
    code: str


class DriverRankingUpdate(BaseModel):
    manual_ranking_score: Optional[float] = None
    manual_rank_note: Optional[str] = None


class DriverProfileUpdate(BaseModel):
    name: str
    phone: str
    email: EmailStr
    new_password: Optional[str] = None


class DriverSelfProfileUpdate(BaseModel):
    first_name: str
    last_name: str
    birth_date: Optional[str] = None
    gender: Optional[Literal["masculin", "feminin"]] = None
    cnp: Optional[str] = None
    phone: str
    email: EmailStr


class DriverStatusUpdate(BaseModel):
    status: DriverOperationalStatus
    break_minutes: Optional[int] = None


class DriverAvatarModeration(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = None


class DriverDisableUpdate(BaseModel):
    reason: Optional[str] = None
