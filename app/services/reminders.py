"""
APScheduler background job: appointment reminders.

================================================================================
WHY APSCHEDULER INSTEAD OF CELERY FOR THIS SCALE?
================================================================================
Celery strengths:
  - Distributed task queues, retries, routing, horizontal worker fleets
  - Needs a broker (Redis/RabbitMQ) + result backend + separate worker processes

APScheduler strengths for a portfolio / early-stage app:
  - Runs inside the FastAPI process (one less moving part to deploy on EC2)
  - Perfect for periodic "scan DB + notify" jobs every N minutes
  - Zero extra infrastructure beyond what we already have

When you'd switch to Celery / SQS + Lambda / EventBridge:
  - Reminder fan-out to millions of users
  - Need guaranteed at-least-once delivery with dead-letter queues
  - Long-running or CPU-heavy tasks that shouldn't share the API process
  - Multiple heterogeneous job types with different SLAs

For interview answer: "Start simple (APScheduler). Extract to Celery/SQS when
the job volume or reliability requirements outgrow in-process scheduling."
================================================================================
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.database import SessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")

# Track which appointments we've already reminded about in this process so we
# don't spam logs every interval. In production you'd store `reminder_sent_at`
# on the appointments row (or a notifications table).
_reminded_ids: set[int] = set()


def send_appointment_reminders() -> None:
    """
    Find appointments starting within the next REMINDER_LOOKAHEAD_HOURS and
    "send" a reminder (log line — swap for SendGrid/SES in production).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=settings.reminder_lookahead_hours)

    db = SessionLocal()
    try:
        upcoming = (
            db.query(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor).joinedload(Doctor.user),
                joinedload(Appointment.slot),
            )
            .filter(
                Appointment.status.in_(
                    [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
                )
            )
            .all()
        )

        sent = 0
        for appt in upcoming:
            if appt.id in _reminded_ids:
                continue
            if appt.slot is None:
                continue
            start = appt.slot.start_time
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if now <= start <= horizon:
                # --- Simulated notification channel ---
                # Replace with SendGrid / AWS SES / SNS:
                #   send_email(to=appt.patient.email, subject=..., body=...)
                logger.info(
                    "[REMINDER] Appointment #%s for patient '%s' <%s> with "
                    "Dr. %s (%s) starts at %s (status=%s)",
                    appt.id,
                    appt.patient.name if appt.patient else "?",
                    appt.patient.email if appt.patient else "?",
                    appt.doctor.user.name if appt.doctor and appt.doctor.user else "?",
                    appt.doctor.specialization if appt.doctor else "?",
                    start.isoformat(),
                    appt.status.value,
                )
                _reminded_ids.add(appt.id)
                sent += 1

        if sent:
            logger.info("Reminder job sent %s notification(s)", sent)
        else:
            logger.debug("Reminder job: nothing new to send")
    finally:
        db.close()


def start_scheduler() -> None:
    settings = get_settings()
    if scheduler.running:
        return
    scheduler.add_job(
        send_appointment_reminders,
        trigger=IntervalTrigger(minutes=settings.reminder_job_interval_minutes),
        id="appointment_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "APScheduler started — reminders every %s minute(s), lookahead %s hour(s)",
        settings.reminder_job_interval_minutes,
        settings.reminder_lookahead_hours,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
