"""
User model — patients, doctors, and admins share one table with a role enum.

Interview note:
- Single-table role design keeps auth simple (one JWT subject type).
- Doctor-specific fields live in `doctors` (1:1 with user) so patient rows
  stay lean and we don't denormalize specialization onto every user.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Optional 1:1 — only populated when role == doctor
    doctor_profile: Mapped["Doctor | None"] = relationship(  # noqa: F821
        "Doctor",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Appointments where this user is the patient
    patient_appointments: Mapped[list["Appointment"]] = relationship(  # noqa: F821
        "Appointment",
        back_populates="patient",
        foreign_keys="Appointment.patient_id",
    )
