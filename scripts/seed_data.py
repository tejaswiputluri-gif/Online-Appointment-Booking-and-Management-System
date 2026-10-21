"""
Seed script — creates demo admin, doctors, patients, and future time slots.

Usage (from project root, with venv active and DB up):
  python -m scripts.seed_data
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python -m scripts.seed_data` from project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth.security import hash_password
from app.database import SessionLocal, init_db
from app.models.doctor import Doctor
from app.models.time_slot import TimeSlot
from app.models.user import User, UserRole


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        # Use example.com — email-validator rejects reserved TLDs like .test
        if db.query(User).filter(User.email == "admin@clinic.example.com").first():
            print("Seed data already present — skipping.")
            return

        # Migrate older seed emails (.test → .example.com) if present
        legacy = db.query(User).filter(User.email == "admin@clinic.test").first()
        if legacy:
            for old, new in (
                ("admin@clinic.test", "admin@clinic.example.com"),
                ("alice@clinic.test", "alice@clinic.example.com"),
                ("bob@clinic.test", "bob@clinic.example.com"),
                ("sarah@clinic.test", "sarah@clinic.example.com"),
                ("james@clinic.test", "james@clinic.example.com"),
            ):
                user = db.query(User).filter(User.email == old).first()
                if user:
                    user.email = new
            db.commit()
            print("Migrated seed emails from .test to .example.com")
            print("Demo logins:")
            print("  admin@clinic.example.com   / AdminPass123!")
            print("  alice@clinic.example.com   / PatientPass123!")
            print("  bob@clinic.example.com     / PatientPass123!")
            print("  sarah@clinic.example.com   / DoctorPass123!")
            print("  james@clinic.example.com   / DoctorPass123!")
            return

        admin = User(
            name="Clinic Admin",
            email="admin@clinic.example.com",
            hashed_password=hash_password("AdminPass123!"),
            role=UserRole.ADMIN,
        )
        patient = User(
            name="Alice Patient",
            email="alice@clinic.example.com",
            hashed_password=hash_password("PatientPass123!"),
            role=UserRole.PATIENT,
        )
        patient2 = User(
            name="Bob Patient",
            email="bob@clinic.example.com",
            hashed_password=hash_password("PatientPass123!"),
            role=UserRole.PATIENT,
        )
        doc_user = User(
            name="Dr. Sarah Chen",
            email="sarah@clinic.example.com",
            hashed_password=hash_password("DoctorPass123!"),
            role=UserRole.DOCTOR,
        )
        doc_user2 = User(
            name="Dr. James Okonkwo",
            email="james@clinic.example.com",
            hashed_password=hash_password("DoctorPass123!"),
            role=UserRole.DOCTOR,
        )
        db.add_all([admin, patient, patient2, doc_user, doc_user2])
        db.flush()

        doctor1 = Doctor(
            user_id=doc_user.id,
            specialization="Cardiology",
            available_days="mon,tue,wed,thu,fri",
        )
        doctor2 = Doctor(
            user_id=doc_user2.id,
            specialization="Dermatology",
            available_days="mon,wed,fri",
        )
        db.add_all([doctor1, doctor2])
        db.flush()

        # Generate slots for the next 5 weekdays, 9:00–12:00 in 30-min blocks
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        slots: list[TimeSlot] = []
        for doctor in (doctor1, doctor2):
            day = now + timedelta(days=1)
            created_days = 0
            while created_days < 5:
                if day.weekday() < 5:  # Mon–Fri
                    for hour in (9, 10, 11):
                        for minute in (0, 30):
                            start = day.replace(hour=hour, minute=minute)
                            end = start + timedelta(minutes=30)
                            slots.append(
                                TimeSlot(
                                    doctor_id=doctor.id,
                                    start_time=start,
                                    end_time=end,
                                    is_booked=False,
                                )
                            )
                    created_days += 1
                day += timedelta(days=1)

        db.add_all(slots)
        db.commit()
        print(f"Seeded users + {len(slots)} time slots.")
        print("Demo logins:")
        print("  admin@clinic.example.com   / AdminPass123!")
        print("  alice@clinic.example.com   / PatientPass123!")
        print("  bob@clinic.example.com     / PatientPass123!")
        print("  sarah@clinic.example.com   / DoctorPass123!")
        print("  james@clinic.example.com   / DoctorPass123!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
