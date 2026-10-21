"""Doctor and time-slot schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TimeSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_time: datetime
    end_time: datetime
    is_booked: bool


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    email: str
    specialization: str
    available_days: str


class DoctorWithSlots(DoctorOut):
    available_slots: List[TimeSlotOut] = Field(default_factory=list)
    # Populated from Redis cache hit/miss for interview demos
    slots_from_cache: Optional[bool] = None
