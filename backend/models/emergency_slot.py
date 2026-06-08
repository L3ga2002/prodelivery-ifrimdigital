from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
import uuid


class EmergencySlotCreate(BaseModel):
    week_start: str  # ISO date of Monday
    day: str  # "monday", "tuesday", etc.
    hour: str  # "12:00"
    total_spots: int  # Number of available spots


class EmergencySlot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    week_start: str
    day: str
    hour: str
    total_spots: int
    claimed_by: List[str] = []  # driver_ids
    claimed_names: List[str] = []  # driver names
    remaining_spots: int = 0
    created_by: str = "admin"  # "admin" or "system" (future auto)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
