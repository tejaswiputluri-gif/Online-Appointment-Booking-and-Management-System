"""
Appointments link a patient, doctor, and exactly one time slot.

Interview note — defense in depth against double-booking:
1. Redis SETNX lock serializes concurrent book attempts (primary UX path).
2. `time_slots.is_booked` is flipped inside the same DB transaction.
3. Application check rejects booking if an active (pending/confirmed) row exists.
4. Optional DB safety: a partial unique index on slot_id WHERE status IN
   ('pending','confirmed') — created in init if you add Alembic later.

We intentionally do NOT put a blanket UNIQUE on slot_id: cancelled appointments
keep history, and the same slot must become bookable again after cancel.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_patient_status", "patient_id", "status"),
        Index("ix_appointments_doctor_status", "doctor_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("time_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AppointmentStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    patient: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="patient_appointments",
        foreign_keys=[patient_id],
    )
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="appointments")  # noqa: F821
    slot: Mapped["TimeSlot"] = relationship("TimeSlot", back_populates="appointments")  # noqa: F821
