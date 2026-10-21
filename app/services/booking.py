"""
Booking service — the heart of conflict prevention.

Flow for book_slot():
  1. Rate-limit check (Redis)
  2. Acquire Redis distributed lock on slot:{id}   ← SET NX EX
  3. Inside lock + DB transaction:
       - Load slot (must exist, must not be booked)
       - Ensure no active appointment already references it
       - Insert appointment (status=pending)
       - Flip slot.is_booked = True
       - Commit
  4. Release lock (context manager __exit__)
  5. Invalidate Redis slots cache + publish WebSocket event

If step 2 fails → 409 "Slot is being booked by another user, try again"
If step 3 finds is_booked → 409 "Slot already booked"
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.time_slot import TimeSlot
from app.models.user import User, UserRole
from app.redis_client.cache import invalidate_slots_cache
from app.redis_client.lock import LockAcquisitionError, slot_lock
from app.redis_client.rate_limit import check_booking_rate_limit
from app.schemas.appointment import AppointmentOut
from app.websocket.manager import publish_slot_event

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


def _to_out(appt: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        patient_id=appt.patient_id,
        doctor_id=appt.doctor_id,
        slot_id=appt.slot_id,
        status=appt.status.value,
        created_at=appt.created_at,
        patient_name=appt.patient.name if appt.patient else None,
        doctor_name=appt.doctor.user.name if appt.doctor and appt.doctor.user else None,
        specialization=appt.doctor.specialization if appt.doctor else None,
        start_time=appt.slot.start_time if appt.slot else None,
        end_time=appt.slot.end_time if appt.slot else None,
    )


def book_slot(db: Session, patient: User, slot_id: int) -> AppointmentOut:
    """
    Book a time slot with Redis distributed locking.

    Only patients (or admin acting as patient flow) should call this —
    enforced at the route layer via require_roles.
    """
    if patient.role == UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctors cannot book appointments as patients via this endpoint.",
        )

    # --- Abuse protection (shared across all app servers via Redis) ---
    check_booking_rate_limit(patient.id)

    # --- Distributed critical section ---
    # Why not just rely on DB?
    #   Two app servers can both SELECT is_booked=false, then both INSERT.
    #   Redis SETNX makes the "who gets to attempt the write" decision
    #   cluster-wide before we touch Postgres.
    try:
        with slot_lock(slot_id):
            return _book_inside_lock(db, patient, slot_id)
    except LockAcquisitionError:
        # Another request is mid-booking this slot. From the loser's POV this
        # is equivalent to "already taken" for UX (they should refresh slots).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Slot is currently being booked by another user. "
                "Please refresh available slots and try a different time."
            ),
        )
    except HTTPException:
        # Propagate domain errors (404 slot missing, 409 already booked, etc.)
        raise
    except Exception as exc:
        # Fail closed: if Redis is down we refuse to book rather than risk a race.
        # (Contrast with rate limiting, which fails open for availability.)
        logger.error("Booking lock infrastructure error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Booking temporarily unavailable (lock service error). Please retry.",
        ) from exc


def _book_inside_lock(db: Session, patient: User, slot_id: int) -> AppointmentOut:
    # IMPORTANT: do NOT combine joinedload() with with_for_update().
    # joinedload emits LEFT OUTER JOINs; Postgres rejects
    # "FOR UPDATE ... on the nullable side of an outer join".
    # Lock only the time_slots row; enrich relationships after commit.
    slot: Optional[TimeSlot] = (
        db.query(TimeSlot)
        .filter(TimeSlot.id == slot_id)
        .with_for_update()  # DB row lock as second line of defense (same Postgres)
        .first()
    )

    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Time slot {slot_id} does not exist.",
        )

    if slot.is_booked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot already booked.",
        )

    existing = (
        db.query(Appointment)
        .filter(
            Appointment.slot_id == slot_id,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if existing:
        # Invariant broken somehow (cache? manual DB edit?) — still refuse
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot already booked.",
        )

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        status=AppointmentStatus.PENDING,
    )
    slot.is_booked = True
    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    # Re-load relationships for response enrichment
    appointment = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor).joinedload(Doctor.user),
            joinedload(Appointment.slot),
        )
        .filter(Appointment.id == appointment.id)
        .one()
    )

    doctor_id = appointment.doctor_id
    # Side effects AFTER commit so we never broadcast a booking that rolled back
    invalidate_slots_cache(doctor_id)
    publish_slot_event(
        doctor_id,
        {
            "event": "slot_booked",
            "slot_id": slot_id,
            "doctor_id": doctor_id,
            "appointment_id": appointment.id,
            "start_time": appointment.slot.start_time if appointment.slot else None,
            "end_time": appointment.slot.end_time if appointment.slot else None,
        },
    )
    logger.info(
        "Booked appointment=%s slot=%s patient=%s doctor=%s",
        appointment.id,
        slot_id,
        patient.id,
        doctor_id,
    )
    return _to_out(appointment)


def cancel_appointment(db: Session, user: User, appointment_id: int) -> AppointmentOut:
    """
    Cancel an appointment and free the slot.

    Authorization:
      - Patient: only their own appointments
      - Doctor: appointments on their schedule
      - Admin: any
    """
    appt = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor).joinedload(Doctor.user),
            joinedload(Appointment.slot),
        )
        .filter(Appointment.id == appointment_id)
        .first()
    )
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appt.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Appointment is already cancelled.")
    if appt.status == AppointmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Completed appointments cannot be cancelled.")

    _assert_can_modify(user, appt)

    # Lock the slot so a concurrent book doesn't race with our free
    try:
        with slot_lock(appt.slot_id):
            appt.status = AppointmentStatus.CANCELLED
            if appt.slot:
                appt.slot.is_booked = False
            db.commit()
            db.refresh(appt)
    except LockAcquisitionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not cancel right now — slot is locked by another operation. Retry.",
        )

    invalidate_slots_cache(appt.doctor_id)
    publish_slot_event(
        appt.doctor_id,
        {
            "event": "slot_freed",
            "slot_id": appt.slot_id,
            "doctor_id": appt.doctor_id,
            "appointment_id": appt.id,
            "start_time": appt.slot.start_time if appt.slot else None,
            "end_time": appt.slot.end_time if appt.slot else None,
        },
    )
    return _to_out(appt)


def update_appointment_status(
    db: Session,
    user: User,
    appointment_id: int,
    new_status: str,
) -> AppointmentOut:
    """Doctor/admin updates status to confirmed or completed (or cancelled)."""
    if user.role not in (UserRole.DOCTOR, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors or admins can update appointment status.",
        )

    try:
        status_enum = AppointmentStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}'.")

    if status_enum == AppointmentStatus.PENDING:
        raise HTTPException(status_code=400, detail="Cannot revert to pending.")

    # Cancel goes through the cancel path so the slot is freed correctly
    if status_enum == AppointmentStatus.CANCELLED:
        return cancel_appointment(db, user, appointment_id)

    appt = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor).joinedload(Doctor.user),
            joinedload(Appointment.slot),
        )
        .filter(Appointment.id == appointment_id)
        .first()
    )
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    if appt.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cancelled appointments cannot be updated.")

    _assert_doctor_owns_or_admin(user, appt)

    appt.status = status_enum
    db.commit()
    db.refresh(appt)
    return _to_out(appt)


def list_my_appointments(db: Session, user: User) -> list[AppointmentOut]:
    """
    Role-aware listing:
      - patient → their bookings
      - doctor  → appointments on their schedule
      - admin   → all appointments
    """
    q = db.query(Appointment).options(
        joinedload(Appointment.patient),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.slot),
    )

    if user.role == UserRole.PATIENT:
        q = q.filter(Appointment.patient_id == user.id)
    elif user.role == UserRole.DOCTOR:
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
        if doctor is None:
            return []
        q = q.filter(Appointment.doctor_id == doctor.id)
    # admin: no filter

    rows = q.order_by(Appointment.created_at.desc()).all()
    return [_to_out(a) for a in rows]


def _assert_can_modify(user: User, appt: Appointment) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.PATIENT and appt.patient_id == user.id:
        return
    if user.role == UserRole.DOCTOR:
        _assert_doctor_owns_or_admin(user, appt)
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not allowed to modify this appointment.",
    )


def _assert_doctor_owns_or_admin(user: User, appt: Appointment) -> None:
    if user.role == UserRole.ADMIN:
        return
    doctor = appt.doctor
    if doctor is None or doctor.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage appointments on your own schedule.",
        )
