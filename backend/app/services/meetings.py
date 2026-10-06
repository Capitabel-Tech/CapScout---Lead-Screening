"""Completing a meeting: history + current values + GPS, in one transaction.

The phone keeps the in-progress draft and submits the finished meeting once.
The meeting id is generated on the phone, so a retried submission (weak
network, offline queue) returns the already-saved meeting instead of creating
a second one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, GpsStatus, Meeting, MeetingStatus, Staff, SyncStatus
from app.services.customers import (
    IDENTITY_KEYS,
    DuplicateOtherStaff,
    InvalidValues,
    OnDuplicate,
    _lock_mobile,
    apply_values,
    audit,
    clean_values,
    resolve_duplicate,
)

MAX_CLOCK_SKEW = timedelta(minutes=10)


class GpsPoint(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    accuracy_m: Decimal = Field(gt=0, le=100_000)
    captured_at: datetime


class MeetingIn(BaseModel):
    id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    gps_start: GpsPoint | None = None
    gps_end: GpsPoint | None = None
    # Required when gps_start is missing: why the location could not be captured.
    gps_unavailable_reason: str | None = Field(default=None, max_length=300)
    # Only the fields touched in this meeting. "" or null clears a field.
    values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("must include a timezone")
        return v

    @model_validator(mode="after")
    def _check(self) -> MeetingIn:
        # Location is never typed by staff: it always comes from the GPS (see app/services/places.py).
        self.values = {k: v for k, v in self.values.items() if k != "location"}
        if self.ended_at < self.started_at:
            raise ValueError("ended_at is before started_at")
        if self.ended_at > datetime.now(UTC) + MAX_CLOCK_SKEW:
            raise ValueError("meeting time is in the future; check the phone's clock")
        reason = (self.gps_unavailable_reason or "").strip()
        if self.gps_start is None and not reason:
            raise ValueError("GPS location or a reason why it is unavailable is required")
        self.gps_unavailable_reason = reason or None
        return self


class MeetingConflict(Exception):
    """The meeting id is already used for a different customer."""


def _set_gps(meeting: Meeting, prefix: str, point: GpsPoint | None) -> None:
    if point is None:
        return
    setattr(meeting, f"{prefix}_latitude", point.latitude)
    setattr(meeting, f"{prefix}_longitude", point.longitude)
    setattr(meeting, f"{prefix}_accuracy_m", point.accuracy_m)
    setattr(meeting, f"{prefix}_captured_at", point.captured_at)


def complete_meeting(db: Session, staff: Staff, customer: Customer, data: MeetingIn) -> tuple[Meeting, bool]:
    """Save a finished meeting. Returns (meeting, created). Commits on success."""
    cleaned = clean_values(data.values, keep_empty=True)

    # Lock the customer row: serialises meetings on the same customer so
    # sequence numbers and current values stay consistent, and so two copies
    # of the same submission cannot both pass the "already saved?" check.
    db.execute(select(Customer.id).where(Customer.id == customer.id).with_for_update())
    db.refresh(customer)

    existing = db.scalar(select(Meeting).where(Meeting.id == data.id))
    if existing is not None:
        db.rollback()
        if existing.customer_id != customer.id:
            raise MeetingConflict()
        return existing, False

    new_mobile = cleaned.get("mobile")
    if new_mobile and new_mobile != customer.mobile_normalized:
        _lock_mobile(db, new_mobile)
        taken = db.scalar(
            select(Customer.id).where(
                Customer.mobile_normalized == new_mobile, Customer.owner_staff_id != customer.owner_staff_id
            )
        )
        if taken:
            audit(db, staff, "DUPLICATE_BLOCKED", customer, {"reason": "assigned_to_other_staff", "in": "meeting"})
            db.commit()
            raise DuplicateOtherStaff()

    changes = apply_values(customer, cleaned)
    meeting = Meeting(
        id=data.id,
        customer_id=customer.id,
        staff_id=staff.id,
        sequence_no=customer.meeting_count + 1,
        status=MeetingStatus.COMPLETED,
        started_at=data.started_at,
        ended_at=data.ended_at,
        changes=changes,
        gps_status=GpsStatus.CAPTURED if data.gps_start else GpsStatus.UNAVAILABLE,
        gps_unavailable_reason=None if data.gps_start else data.gps_unavailable_reason,
        # Every completed meeting goes to Zoho Meetings (the sync worker comes in Phase 5).
        zoho_sync_status=SyncStatus.PENDING,
        zoho_next_attempt_at=datetime.now(UTC),
    )
    _set_gps(meeting, "start", data.gps_start)
    _set_gps(meeting, "end", data.gps_end)
    db.add(meeting)

    customer.meeting_count += 1
    if customer.last_meeting_at is None or data.started_at > customer.last_meeting_at:
        customer.last_meeting_at = data.started_at

    audit(
        db,
        staff,
        "MEETING_COMPLETED",
        customer,
        {"meeting_id": str(meeting.id), "sequence_no": meeting.sequence_no, "changed_fields": len(changes)},
    )
    db.commit()
    db.refresh(meeting)
    return meeting, True


def new_lead_with_meeting(
    db: Session,
    staff: Staff,
    data: MeetingIn,
    on_duplicate: OnDuplicate = OnDuplicate.ASK,
    overwrite_customer_id: uuid.UUID | None = None,
) -> tuple[Customer, Meeting, bool]:
    """"New lead": create the prospect and save its Meeting #1 together.

    All values belong to the meeting, so Meeting #1's history shows everything
    collected. A retried submission returns the records already saved.
    Returns (customer, meeting, created). Commits on success.
    """
    existing = db.get(Meeting, data.id)
    if existing is not None:
        customer = db.get(Customer, existing.customer_id)
        if customer.owner_staff_id != staff.id:
            raise MeetingConflict()
        return customer, existing, False

    cleaned = clean_values(data.values)
    if not any(k in cleaned for k in IDENTITY_KEYS):
        raise InvalidValues({k: "enter at least Business Name, Promoter or Mobile" for k in IDENTITY_KEYS})

    target = resolve_duplicate(db, staff, cleaned.get("mobile"), on_duplicate, overwrite_customer_id)
    if target is None:
        target = Customer(owner_staff_id=staff.id, current_values={})
        db.add(target)
        db.flush()
        audit(db, staff, "PROSPECT_CREATED", target, {"via": "new_lead_meeting"})
    # Overwrite = this meeting's values update the existing customer.
    meeting, _ = complete_meeting(db, staff, target, data)
    return target, meeting, True


def _gps_out(m: Meeting, prefix: str) -> dict[str, Any] | None:
    lat = getattr(m, f"{prefix}_latitude")
    if lat is None:
        return None
    return {
        "latitude": float(lat),
        "longitude": float(getattr(m, f"{prefix}_longitude")),
        "accuracy_m": float(getattr(m, f"{prefix}_accuracy_m")),
        "captured_at": getattr(m, f"{prefix}_captured_at").isoformat(),
    }


def meeting_out(m: Meeting, staff_names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "customer_id": str(m.customer_id),
        "sequence_no": m.sequence_no,
        "staff": {"id": str(m.staff_id), "full_name": staff_names.get(m.staff_id)},
        "started_at": m.started_at.isoformat(),
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "changes": m.changes,
        "gps_status": m.gps_status.value,
        "gps_unavailable_reason": m.gps_unavailable_reason,
        "place": m.start_place,
        "gps_start": _gps_out(m, "start"),
        "gps_end": _gps_out(m, "end"),
        "zoho_sync_status": m.zoho_sync_status.value,
        "zoho_meeting_id": m.zoho_meeting_id,
        "zoho_last_error": m.zoho_last_error,
    }
