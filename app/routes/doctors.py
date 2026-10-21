"""Doctor and slot listing routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.doctor import DoctorOut, DoctorWithSlots, TimeSlotOut
from app.services import doctors as doctor_service

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.get(
    "",
    response_model=list[DoctorWithSlots],
    summary="List all doctors with specialization and available slots",
)
def list_doctors(db: Session = Depends(get_db)) -> list[DoctorWithSlots]:
    return doctor_service.list_doctors(db, include_slots=True)


@router.get(
    "/{doctor_id}",
    response_model=DoctorOut,
    summary="Get a single doctor profile",
)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)) -> DoctorOut:
    doctor = doctor_service.get_doctor_or_404(db, doctor_id)
    return doctor_service.doctor_to_out(doctor)


@router.get(
    "/{doctor_id}/slots",
    response_model=list[TimeSlotOut],
    summary="Get available (unbooked) time slots for a doctor",
)
def get_doctor_slots(doctor_id: int, db: Session = Depends(get_db)) -> list[TimeSlotOut]:
    slots, _from_cache = doctor_service.get_available_slots(db, doctor_id)
    return slots
