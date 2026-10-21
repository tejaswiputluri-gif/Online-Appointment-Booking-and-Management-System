"""
Appointment routes — booking uses Redis distributed lock + rate limiting.

Interview talking point: the HTTP layer stays thin; concurrency logic lives in
services/booking.py so it can be unit-tested without FastAPI.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, DoctorUser, PatientUser
from app.database import get_db
from app.schemas.appointment import (
    AppointmentBookRequest,
    AppointmentOut,
    AppointmentStatusUpdate,
)
from app.services import booking as booking_service

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post(
    "/book",
    response_model=AppointmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book a slot (Redis SETNX lock + rate limit)",
)
def book_appointment(
    body: AppointmentBookRequest,
    user: PatientUser,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    """
    Patients book a free slot. Concurrent requests for the same slot_id are
    serialized by a Redis distributed lock (see app/redis_client/lock.py).
    """
    return booking_service.book_slot(db, user, body.slot_id)


@router.patch(
    "/{appointment_id}/cancel",
    response_model=AppointmentOut,
    summary="Cancel an appointment and free the slot",
)
def cancel_appointment(
    appointment_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    return booking_service.cancel_appointment(db, user, appointment_id)


@router.get(
    "/my",
    response_model=list[AppointmentOut],
    summary="List appointments for the logged-in user (role-aware)",
)
def my_appointments(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[AppointmentOut]:
    return booking_service.list_my_appointments(db, user)


@router.patch(
    "/{appointment_id}/status",
    response_model=AppointmentOut,
    summary="Doctor/admin updates appointment status",
)
def update_status(
    appointment_id: int,
    body: AppointmentStatusUpdate,
    user: DoctorUser,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    return booking_service.update_appointment_status(
        db, user, appointment_id, body.status
    )
