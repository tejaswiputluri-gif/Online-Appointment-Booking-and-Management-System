"""Appointment request/response schemas."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AppointmentBookRequest(BaseModel):
    slot_id: int = Field(..., gt=0, description="ID of the time_slots row to book")


class AppointmentStatusUpdate(BaseModel):
    status: Literal["confirmed", "completed", "cancelled"]


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    slot_id: int
    status: str
    created_at: datetime
    # Enriched fields for nicer API responses
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    specialization: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
