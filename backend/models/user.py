from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, timezone
import uuid


class UserBase(BaseModel):
    email: str
    name: str
    role: str
    phone: Optional[str] = None
    restaurant_id: Optional[str] = None
    restaurant_name: Optional[str] = None


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str
    phone: Optional[str] = None
    restaurant_id: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class User(UserBase):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
