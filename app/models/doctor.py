"""
Doctor profile — extends a user with clinical metadata.

`available_days` is stored as a comma-separated string (e.g. "mon,tue,wed")
for simplicity in a portfolio project. In production you'd often use a
JSON/array column or a separate schedule table for timezone-aware hours.
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    specialization: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # e.g. "mon,tue,wed,thu,fri"
    available_days: Mapped[str] = mapped_column(Text, nullable=False, default="mon,tue,wed,thu,fri")

    user: Mapped["User"] = relationship("User", back_populates="doctor_profile")  # noqa: F821
    time_slots: Mapped[list["TimeSlot"]] = relationship(  # noqa: F821
        "TimeSlot",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list["Appointment"]] = relationship(  # noqa: F821
        "Appointment",
        back_populates="doctor",
    )
