"""Customer creation, current values and the duplicate-mobile rule.

Duplicate rule (client decision):
  * Mobile already belongs to ANOTHER staff member -> blocked, no details shown.
  * Mobile already belongs to the SAME staff member -> show the match and let
    them choose Overwrite existing / Create new / Cancel.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.fields.catalog import FieldValueError, clean_value, load_catalog
from app.models import AuditLog, Customer, Staff

IDENTITY_KEYS = ("business_name", "promoter", "mobile")
SUMMARY_KEYS = ("business_name", "promoter", "mobile", "loan_required", "purpose", "likely_product")


class OnDuplicate(str, enum.Enum):
    ASK = "ask"
    CREATE_NEW = "create_new"
    OVERWRITE = "overwrite"


class DuplicateOtherStaff(Exception):
    pass


class DuplicateOwn(Exception):
    def __init__(self, matches: list[Customer]):
        super().__init__("duplicate mobile")
        self.matches = matches


class InvalidValues(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__(errors)
        self.errors = errors


def clean_values(raw: dict[str, Any], keep_empty: bool = False) -> dict[str, Any]:
    """Validate every value. Raises InvalidValues.

    Empty values are dropped, or kept as None ("clear this field") when
    keep_empty is set, which is how a meeting corrects a wrong entry.
    """
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in raw.items():
        try:
            v = clean_value(key, value)
        except FieldValueError as e:
            errors[e.key] = e.message
            continue
        if v is not None or keep_empty:
            cleaned[key] = v
    if errors:
        raise InvalidValues(errors)
    return cleaned


def apply_values(customer: Customer, cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge cleaned values into the customer's current state.

    Returns one {"field", "old", "new", "type"} entry per value that actually
    changed (type NEW, UPDATED or CLEARED); callers store these as meeting
    history (or in the audit log). A None value clears the field.
    """
    current = dict(customer.current_values or {})
    changes: list[dict[str, Any]] = []
    for key, new in cleaned.items():
        old = current.get(key)
        if old == new:
            continue
        if new is None:
            del current[key]
            change_type = "CLEARED"
        else:
            current[key] = new
            change_type = "NEW" if old is None else "UPDATED"
        changes.append({"field": key, "old": old, "new": new, "type": change_type})

    # Assign a new dict so SQLAlchemy notices the JSONB change.
    customer.current_values = current
    progress_keys = {f.key for f in load_catalog().fields if f.counts_toward_progress}
    customer.fields_filled_count = sum(1 for k in current if k in progress_keys)
    if "mobile" in cleaned:
        customer.mobile_normalized = cleaned["mobile"]  # None when cleared
    return changes


def audit(db: Session, staff: Staff, action: str, customer: Customer | None, details: dict | None = None) -> None:
    db.add(
        AuditLog(
            staff_id=staff.id,
            action=action,
            entity_type="customer" if customer else None,
            entity_id=str(customer.id) if customer else None,
            details=details,
        )
    )


def _lock_mobile(db: Session, mobile: str) -> None:
    # Serialise concurrent creates for the same number until this transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"mobile:{mobile}"})


def resolve_duplicate(
    db: Session,
    staff: Staff,
    mobile: str | None,
    on_duplicate: OnDuplicate,
    overwrite_customer_id: uuid.UUID | None,
) -> Customer | None:
    """Apply the duplicate-mobile rule before creating a prospect.

    Returns the staff member's own customer to overwrite, or None to create a
    new one. Raises DuplicateOtherStaff / DuplicateOwn / InvalidValues.
    """
    if not mobile:
        return None
    _lock_mobile(db, mobile)
    matches = db.scalars(select(Customer).where(Customer.mobile_normalized == mobile)).all()
    if any(m.owner_staff_id != staff.id for m in matches):
        audit(db, staff, "DUPLICATE_BLOCKED", None, {"reason": "assigned_to_other_staff"})
        db.commit()
        raise DuplicateOtherStaff()
    if not matches or on_duplicate == OnDuplicate.CREATE_NEW:
        return None
    if on_duplicate == OnDuplicate.ASK:
        raise DuplicateOwn(list(matches))
    target = next((m for m in matches if m.id == overwrite_customer_id), None)
    if target is None:
        raise InvalidValues({"overwrite_customer_id": "choose one of the matching records"})
    return target


def create_prospect(
    db: Session,
    staff: Staff,
    raw_values: dict[str, Any],
    on_duplicate: OnDuplicate = OnDuplicate.ASK,
    overwrite_customer_id: uuid.UUID | None = None,
) -> tuple[Customer, bool]:
    """Create a prospect, or overwrite one of the staff member's own matches.

    Returns (customer, created). Commits on success.
    """
    cleaned = clean_values({k: v for k, v in raw_values.items() if k != "location"})  # Location comes from GPS only
    if not any(k in cleaned for k in IDENTITY_KEYS):
        raise InvalidValues({k: "enter at least Business Name, Promoter or Mobile" for k in IDENTITY_KEYS})

    mobile = cleaned.get("mobile")
    target = resolve_duplicate(db, staff, mobile, on_duplicate, overwrite_customer_id)
    if target is not None:
        changes = apply_values(target, cleaned)
        audit(db, staff, "PROSPECT_OVERWRITTEN", target, {"changes": changes})
        db.commit()
        return target, False

    customer = Customer(owner_staff_id=staff.id, current_values={})
    db.add(customer)
    changes = apply_values(customer, cleaned)
    db.flush()
    audit(
        db,
        staff,
        "PROSPECT_CREATED",
        customer,
        {"fields": [c["field"] for c in changes], "duplicate_choice": on_duplicate.value if mobile else None},
    )
    db.commit()
    db.refresh(customer)
    return customer, True


def summary(customer: Customer) -> dict[str, Any]:
    vals = customer.current_values or {}
    return {k: vals.get(k) for k in SUMMARY_KEYS}
