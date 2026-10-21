"""Doctor listing and available-slot queries (with Redis cache)."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models.doctor import Doctor
from app.models.time_slot import TimeSlot
from app.redis_client.cache import get_cached_slots, set_cached_slots
from app.schemas.doctor import DoctorOut, DoctorWithSlots, TimeSlotOut


def doctor_to_out(doctor: Doctor) -> DoctorOut:
    return DoctorOut(
        id=doctor.id,
        user_id=doctor.user_id,
        name=doctor.user.name,
        email=doctor.user.email,
        specialization=doctor.specialization,
        available_days=doctor.available_days,
    )


def list_doctors(db: Session, include_slots: bool = True) -> list[DoctorWithSlots]:
    doctors = (
        db.query(Doctor)
        .options(joinedload(Doctor.user))
        .order_by(Doctor.id)
        .all()
    )
    result: list[DoctorWithSlots] = []
    for d in doctors:
        base = doctor_to_out(d)
        slots: list[TimeSlotOut] = []
        from_cache: Optional[bool] = None
        if include_slots:
            slots, from_cache = get_available_slots(db, d.id)
        result.append(
            DoctorWithSlots(
                **base.model_dump(),
                available_slots=slots,
                slots_from_cache=from_cache,
            )
        )
    return result


def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = (
        db.query(Doctor)
        .options(joinedload(Doctor.user))
        .filter(Doctor.id == doctor_id)
        .first()
    )
    if doctor is None:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found.")
    return doctor


def get_available_slots(
    db: Session,
    doctor_id: int,
) -> tuple[list[TimeSlotOut], bool]:
    """
    Return (slots, served_from_cache).

    Cache is invalidated on book/cancel; TTL is a safety net.
    """
    get_doctor_or_404(db, doctor_id)

    cached = get_cached_slots(doctor_id)
    if cached is not None:
        return [TimeSlotOut(**row) for row in cached], True

    rows = (
        db.query(TimeSlot)
        .filter(TimeSlot.doctor_id == doctor_id, TimeSlot.is_booked.is_(False))
        .order_by(TimeSlot.start_time)
        .all()
    )
    slots = [TimeSlotOut.model_validate(r) for r in rows]
    set_cached_slots(doctor_id, [s.model_dump(mode="json") for s in slots])
    return slots, False
