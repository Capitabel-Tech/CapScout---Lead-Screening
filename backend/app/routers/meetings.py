import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.access import get_visible_customer
from app.auth import CurrentStaff, DbSession
from app.models import AuditLog, Meeting, Staff, SyncStatus
from app.routers.customers import OTHER_STAFF_MESSAGE
from app.services.customers import DuplicateOtherStaff, DuplicateOwn, InvalidValues, OnDuplicate, summary
from app.services.meetings import (
    MeetingConflict,
    MeetingIn,
    complete_meeting,
    meeting_out,
    new_lead_with_meeting,
)

router = APIRouter(prefix="/customers/{customer_id}/meetings", tags=["meetings"])
new_lead_router = APIRouter(tags=["meetings"])


def _staff_names(db, meetings: list[Meeting]) -> dict:
    ids = {m.staff_id for m in meetings}
    if not ids:
        return {}
    return dict(db.execute(select(Staff.id, Staff.full_name).where(Staff.id.in_(ids))).all())


@router.get("")
def list_meetings(customer_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> dict:
    customer = get_visible_customer(db, staff, customer_id)
    meetings = db.scalars(
        select(Meeting).where(Meeting.customer_id == customer.id).order_by(Meeting.sequence_no.desc())
    ).all()
    names = _staff_names(db, meetings)
    return {"items": [meeting_out(m, names) for m in meetings]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_meeting(customer_id: uuid.UUID, body: MeetingIn, staff: CurrentStaff, db: DbSession):
    customer = get_visible_customer(db, staff, customer_id)
    try:
        meeting, created = complete_meeting(db, staff, customer, body)
    except InvalidValues as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "INVALID_VALUES", "errors": e.errors}) from None
    except DuplicateOtherStaff:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSIGNED_TO_OTHER_STAFF", "message": OTHER_STAFF_MESSAGE, "field": "mobile"},
        ) from None
    except MeetingConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "MEETING_ID_CONFLICT"}) from None

    out = meeting_out(meeting, _staff_names(db, [meeting]))
    # 200 tells the phone "already saved earlier" (a safe retry), 201 "saved now".
    return out if created else JSONResponse(status_code=200, content=out)


@router.post("/{meeting_id}/retry-sync")
def retry_meeting_sync(customer_id: uuid.UUID, meeting_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> dict:
    """"Retry Sync" button: put a failed meeting back in the Zoho queue."""
    customer = get_visible_customer(db, staff, customer_id)
    meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.customer_id == customer.id))
    if meeting is None:
        raise HTTPException(status_code=404, detail="Not found")
    if meeting.zoho_sync_status == SyncStatus.FAILED:
        meeting.zoho_sync_status = SyncStatus.PENDING
        meeting.zoho_attempts = 0
        meeting.zoho_last_error = None
        meeting.zoho_next_attempt_at = datetime.now(UTC)
        db.add(AuditLog(staff_id=staff.id, action="ZOHO_SYNC_RETRY", entity_type="meeting", entity_id=str(meeting.id)))
        db.commit()
        db.refresh(meeting)
    return meeting_out(meeting, _staff_names(db, [meeting]))


class NewLeadIn(BaseModel):
    meeting: MeetingIn
    on_duplicate: OnDuplicate = OnDuplicate.ASK
    overwrite_customer_id: uuid.UUID | None = None


@new_lead_router.post("/leads/new", status_code=status.HTTP_201_CREATED)
def create_new_lead(body: NewLeadIn, staff: CurrentStaff, db: DbSession):
    """The prototype's "New lead" flow: prospect + Meeting #1 in one step."""
    try:
        customer, meeting, created = new_lead_with_meeting(
            db, staff, body.meeting, body.on_duplicate, body.overwrite_customer_id
        )
    except InvalidValues as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "INVALID_VALUES", "errors": e.errors}) from None
    except DuplicateOtherStaff:
        raise HTTPException(
            status_code=409, detail={"code": "ASSIGNED_TO_OTHER_STAFF", "message": OTHER_STAFF_MESSAGE}
        ) from None
    except DuplicateOwn as e:
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "DUPLICATE_OWN",
                    "message": "A customer with this mobile number already exists.",
                    "choices": ["overwrite", "create_new", "cancel"],
                    "matches": [
                        {
                            "id": str(m.id),
                            "lead_ref": m.lead_ref,
                            "conversion_status": m.conversion_status.value,
                            "last_meeting_at": m.last_meeting_at.isoformat() if m.last_meeting_at else None,
                            **summary(m),
                        }
                        for m in e.matches
                    ],
                }
            },
        )
    except MeetingConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "MEETING_ID_CONFLICT"}) from None

    out = {"customer_id": str(customer.id), "meeting": meeting_out(meeting, _staff_names(db, [meeting]))}
    return out if created else JSONResponse(status_code=200, content=out)
