"""Zoho sync rules (the core business logic of the integration).

  Not converted : meeting -> Zoho Meetings (Events). NO Lead is created.
  Convert       : create the Lead, save its id, link the earlier meetings to it.
  Converted     : meeting -> Zoho Meetings linked to the Lead, and the Lead is updated.

Duplicate protection: every Zoho id is saved the moment Zoho returns it, and later
attempts UPDATE BY ID. Before the first create we search Zoho in case an earlier
attempt succeeded but its reply was lost. (Zoho's own upsert duplicate check was
found NOT to be reliable, so it is never used.)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, ConversionStatus, Customer, FieldDefinition, Meeting, Staff, SyncStatus
from app.services.conversion import lead_created, lead_creation_failed
from app.zoho import leadform
from app.zoho.client import Zoho, ZohoError, first_id, records_from
from app.zoho.payloads import (
    build_event_payload,
    build_lead_payload,
    escape_criteria,
    event_title,
    lead_description,
    merge_description,
)

log = logging.getLogger("zoho.sync")

LEASE = timedelta(minutes=10)  # a claimed job that never reports back becomes due again after this
BACKOFF = [timedelta(minutes=m) for m in (1, 5, 15, 60, 360, 720, 1440)]
BATCH = 100  # Zoho accepts up to 100 records per call


def retry_delay(attempts: int) -> timedelta:
    return BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]


def _now() -> datetime:
    return datetime.now(UTC)


# --- claiming work -------------------------------------------------------------


def claim_due_customers(db: Session, limit: int = 10) -> list[uuid.UUID]:
    now = _now()
    rows = db.scalars(
        select(Customer)
        .where(
            Customer.conversion_status == ConversionStatus.CONVERTING,
            Customer.zoho_sync_status.in_([SyncStatus.PENDING, SyncStatus.SYNCING, SyncStatus.FAILED]),
            Customer.zoho_next_attempt_at.is_not(None),
            Customer.zoho_next_attempt_at <= now,
        )
        .order_by(Customer.zoho_next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for c in rows:
        c.zoho_sync_status = SyncStatus.SYNCING
        c.zoho_next_attempt_at = now + LEASE
    db.commit()
    return [c.id for c in rows]


def claim_due_meetings(db: Session, limit: int = 20) -> list[uuid.UUID]:
    now = _now()
    rows = db.scalars(
        select(Meeting)
        .where(
            Meeting.zoho_sync_status.in_([SyncStatus.PENDING, SyncStatus.SYNCING, SyncStatus.FAILED]),
            Meeting.zoho_next_attempt_at.is_not(None),
            Meeting.zoho_next_attempt_at <= now,
        )
        .order_by(Meeting.zoho_next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for m in rows:
        m.zoho_sync_status = SyncStatus.SYNCING
        m.zoho_next_attempt_at = now + LEASE
    db.commit()
    return [m.id for m in rows]


def release_stale_claims(db: Session) -> int:
    """After a (re)start: items left SYNCING by a pass that never finished are due again at once.

    Safe because every step is duplicate-proof (Zoho ids are saved the moment they are returned, and a
    retry searches Zoho before creating). Without this they would wait out the 10-minute lease.
    """
    now = _now()
    released = 0
    for model in (Customer, Meeting):
        rows = db.scalars(
            select(model).where(model.zoho_sync_status == SyncStatus.SYNCING).with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.zoho_next_attempt_at = now
            released += 1
    db.commit()
    return released


# --- helpers -----------------------------------------------------------------------


def _mapping(db: Session) -> dict[str, str]:
    rows = db.execute(
        select(FieldDefinition.key, FieldDefinition.zoho_api_name).where(FieldDefinition.zoho_api_name.is_not(None))
    ).all()
    return {k: v for k, v in rows if v}


def _audit(db: Session, action: str, entity_type: str, entity_id: Any, details: dict[str, Any]) -> None:
    db.add(AuditLog(action=action, entity_type=entity_type, entity_id=str(entity_id), details=details))


def _body(*records: dict[str, Any]) -> dict[str, Any]:
    return {"data": list(records)}


async def _find_event(zoho: Zoho, cfg: Settings, meeting: Meeting, customer: Customer) -> str | None:
    """Did an earlier attempt already create this meeting in Zoho (reply lost)?"""
    if cfg.zoho_meeting_ref_field:
        criteria = f"({cfg.zoho_meeting_ref_field}:equals:{escape_criteria(str(meeting.id))})"
    else:
        criteria = f"(Event_Title:equals:{escape_criteria(event_title(meeting, customer)[:255])})"
    res = await zoho.call(
        "searchRecords",
        {"path_variables": {"module": "Events"}, "query_params": {"criteria": criteria, "fields": "id"}},
    )
    found = records_from(res)
    return str(found[0]["id"]) if found else None


async def _find_lead(zoho: Zoho, cfg: Settings, customer: Customer) -> str | None:
    if not cfg.zoho_lead_ref_field:
        return None  # no safe natural key without our own id field in Zoho
    criteria = f"({cfg.zoho_lead_ref_field}:equals:{escape_criteria(customer.lead_ref)})"
    res = await zoho.call(
        "searchRecords",
        {"path_variables": {"module": "Leads"}, "query_params": {"criteria": criteria, "fields": "id"}},
    )
    found = records_from(res)
    return str(found[0]["id"]) if found else None


async def _link_events(zoho: Zoho, event_ids: list[str], lead_zoho_id: str) -> None:
    for i in range(0, len(event_ids), BATCH):
        chunk = event_ids[i : i + BATCH]
        res = await zoho.call(
            "updateRecords",
            {
                "path_variables": {"module": "Events"},
                "body": _body(*({"id": eid, "$se_module": "Leads", "What_Id": {"id": lead_zoho_id}} for eid in chunk)),
            },
        )
        for item in records_from(res):
            if item.get("code") not in (None, "SUCCESS"):
                raise ZohoError(f"{item.get('code')}: {item.get('message')}", item.get("code"))


# --- one meeting ------------------------------------------------------------------------


async def sync_meeting(db: Session, zoho: Zoho, cfg: Settings, meeting_id: uuid.UUID) -> None:
    meeting = db.get(Meeting, meeting_id)
    customer = db.get(Customer, meeting.customer_id)
    staff = db.get(Staff, meeting.staff_id)
    try:
        lead_at_start = customer.zoho_lead_id
        found_existing = False
        if not meeting.zoho_meeting_id:
            existing = await _find_event(zoho, cfg, meeting, customer)
            if existing:
                meeting.zoho_meeting_id, found_existing = existing, True
            else:
                payload = build_event_payload(meeting, customer, staff.full_name, cfg, lead_at_start)
                res = await zoho.call(
                    "createRecords", {"path_variables": {"module": "Events"}, "body": _body(payload)}
                )
                meeting.zoho_meeting_id = first_id(res)
            db.commit()  # the Zoho id is saved before anything else can fail

        # The Lead may have been created while we were syncing: make sure the link exists.
        db.refresh(customer)
        if customer.zoho_lead_id and (found_existing or customer.zoho_lead_id != lead_at_start):
            await _link_events(zoho, [meeting.zoho_meeting_id], customer.zoho_lead_id)

        # Converted lead: keep the Zoho Lead current, without overwriting what staff confirmed.
        #  - mapped Zoho fields: ONLY the ones this meeting changed (and only for meetings made
        #    after the conversion; earlier ones are already in the form the staff member confirmed)
        #  - the Description: only the app's labelled block is refreshed, text around it is kept
        if (
            customer.conversion_status == ConversionStatus.CONVERTED
            and customer.zoho_lead_id
            and customer.converted_at is not None
        ):
            payload: dict = {}
            if meeting.created_at > customer.converted_at:
                fields = await leadform.load_lead_fields(cfg, zoho)
                payload = leadform.update_payload(fields, meeting, customer, _mapping(db))
            current = await zoho.call(
                "getRecord", {"path_variables": {"module": "Leads", "recordId": customer.zoho_lead_id}}
            )
            rows = records_from(current)
            old_description = (rows[0].get("Description") if rows else None) or None
            new_description = merge_description(old_description, lead_description(customer))
            if new_description is not None and new_description != old_description:
                payload["Description"] = new_description
            if payload:
                res = await zoho.call(
                    "updateRecord",
                    {
                        "path_variables": {"module": "Leads", "recordId": customer.zoho_lead_id},
                        "body": _body(payload),
                    },
                )
                first_id(res)

        meeting.zoho_sync_status = SyncStatus.SYNCED
        meeting.zoho_last_error = None
        meeting.zoho_next_attempt_at = None
        _audit(db, "ZOHO_SYNC_MEETING_OK", "meeting", meeting.id, {"zoho_meeting_id": meeting.zoho_meeting_id})
        db.commit()
    except Exception as e:  # noqa: BLE001 - every failure is recorded and retried
        db.rollback()
        meeting = db.get(Meeting, meeting_id)
        meeting.zoho_attempts += 1
        meeting.zoho_last_error = str(e)[:2000]
        meeting.zoho_sync_status = SyncStatus.FAILED
        final = meeting.zoho_attempts >= cfg.zoho_max_attempts
        meeting.zoho_next_attempt_at = None if final else _now() + retry_delay(meeting.zoho_attempts)
        _audit(
            db,
            "ZOHO_SYNC_MEETING_FAILED",
            "meeting",
            meeting_id,
            {"attempt": meeting.zoho_attempts, "error": str(e)[:500], "gave_up": final},
        )
        db.commit()
        log.warning("meeting %s sync failed (attempt %s): %s", meeting_id, meeting.zoho_attempts, e)


# --- one conversion ---------------------------------------------------------------------


async def sync_conversion(db: Session, zoho: Zoho, cfg: Settings, customer_id: uuid.UUID) -> None:
    customer = db.get(Customer, customer_id)
    try:
        if not customer.zoho_lead_id:
            lead_id = await _find_lead(zoho, cfg, customer)
            if not lead_id:
                # The values the staff member confirmed on the Convert form; else a default built from our data.
                payload = dict(customer.zoho_lead_payload or build_lead_payload(customer, _mapping(db), cfg))
                if cfg.zoho_lead_ref_field:
                    payload[cfg.zoho_lead_ref_field] = customer.lead_ref
                res = await zoho.call("createRecords", {"path_variables": {"module": "Leads"}, "body": _body(payload)})
                lead_id = first_id(res)
            customer.zoho_lead_id = lead_id
            db.commit()  # saved before anything else can fail

        # Earlier meetings now belong to the Lead.
        event_ids = list(
            db.scalars(
                select(Meeting.zoho_meeting_id).where(
                    Meeting.customer_id == customer.id, Meeting.zoho_meeting_id.is_not(None)
                )
            )
        )
        if event_ids:
            await _link_events(zoho, event_ids, customer.zoho_lead_id)

        lead_created(db, customer, customer.zoho_lead_id)
        _audit(db, "ZOHO_LEAD_CREATED", "customer", customer.id, {"zoho_lead_id": customer.zoho_lead_id})
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        customer = db.get(Customer, customer_id)
        final = customer.zoho_attempts + 1 >= cfg.zoho_max_attempts
        lead_creation_failed(
            db, customer, str(e), final=final, retry_at=_now() + retry_delay(customer.zoho_attempts + 1)
        )
        _audit(
            db,
            "ZOHO_LEAD_FAILED",
            "customer",
            customer_id,
            {"attempt": customer.zoho_attempts, "error": str(e)[:500], "gave_up": final},
        )
        db.commit()
        log.warning("conversion of %s failed (attempt %s): %s", customer_id, customer.zoho_attempts, e)


# --- one pass over everything that is due -------------------------------------------------


async def process(session_factory, zoho: Zoho, cfg: Settings, customer_ids: list[uuid.UUID], meeting_ids: list[uuid.UUID]) -> None:
    # Conversions first, so the Lead exists before its meetings are linked.
    for cid in customer_ids:
        with session_factory() as db:
            await sync_conversion(db, zoho, cfg, cid)
    for mid in meeting_ids:
        with session_factory() as db:
            await sync_meeting(db, zoho, cfg, mid)
