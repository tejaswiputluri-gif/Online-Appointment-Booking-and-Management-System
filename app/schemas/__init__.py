"""Pydantic schemas for request/response validation."""

from app.schemas.appointment import (
    AppointmentBookRequest,
    AppointmentOut,
    AppointmentStatusUpdate,
)
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.doctor import DoctorOut, DoctorWithSlots, TimeSlotOut
from app.schemas.user import UserOut

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "UserOut",
    "DoctorOut",
    "DoctorWithSlots",
    "TimeSlotOut",
    "AppointmentBookRequest",
    "AppointmentOut",
    "AppointmentStatusUpdate",
]
