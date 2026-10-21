"""
Time slots that patients can book.

Interview note — why `is_booked` AND a unique appointment.slot_id?
- `is_booked` is a denormalized flag for fast "available slots" queries
  and Redis cache invalidation without joining appointments.
- The appointments table still owns the booking record (status lifecycle).
- We ALSO rely on Redis distributed locks at write time because under
  concurrent load, two transactions can both read is_booked=False before
  either commits — a classic check-then-act race. See redis_client/lock.py.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimeSlot(Base):
    __tablename__ = "time_slots"
    __table_args__ = (
        # A doctor cannot have two identical start times
        UniqueConstraint("doctor_id", "start_time", name="uq_doctor_start_time"),
        Index("ix_time_slots_doctor_available", "doctor_id", "is_booked"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="time_slots")  # noqa: F821
    # List (not 1:1): after cancel+rebook a slot can have multiple historical rows
    appointments: Mapped[list["Appointment"]] = relationship(  # noqa: F821
        "Appointment",
        back_populates="slot",
    )
