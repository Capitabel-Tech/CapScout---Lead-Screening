"""Database schema: 5 tables.

staff              who uses the app
field_definitions  the 44 Excel fields (with their mobile section)
customers          one row per prospect: CURRENT values + lead conversion + Zoho Lead sync
meetings           one row per visit: HISTORY (what changed) + GPS + Zoho Meeting sync
audit_log          who did what, including every Zoho sync attempt

A meeting's `changes` are written once when it is completed and never
rewritten, so history survives later edits to `customers.current_values`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _enum(cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR + CHECK so adding a value later is a simple migration.
    return Enum(
        cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        create_constraint=True,
        name=f"ck_{cls.__name__.lower()}",
    )


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --- enums -----------------------------------------------------------------


class StaffRole(str, enum.Enum):
    FIELD_STAFF = "FIELD_STAFF"
    SUPERVISOR = "SUPERVISOR"  # team view is a future improvement
    ADMIN = "ADMIN"


class FieldType(str, enum.Enum):
    SYSTEM = "system"
    TEXT = "text"
    LONG_TEXT = "long_text"
    PHONE = "phone"
    NUMBER = "number"
    DATE = "date"
    SINGLE_SELECT = "single_select"


class ConversionStatus(str, enum.Enum):
    NOT_CONVERTED = "NOT_CONVERTED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"
    CONVERSION_FAILED = "CONVERSION_FAILED"


class MeetingStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"


class GpsStatus(str, enum.Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    UNAVAILABLE = "UNAVAILABLE"  # saved without GPS; reason is mandatory


class SyncStatus(str, enum.Enum):
    NOT_QUEUED = "NOT_QUEUED"
    PENDING = "PENDING"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


# --- 1. staff ----------------------------------------------------------------


class Staff(Timestamped, Base):
    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # stored upper-case
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # argon2
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[StaffRole] = mapped_column(_enum(StaffRole), nullable=False, default=StaffRole.FIELD_STAFF)
    # Set when the staff member has their own Zoho login; otherwise records are
    # owned by the integration user in Zoho.
    zoho_user_id: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# --- 2. field_definitions ------------------------------------------------------


class FieldDefinition(Base):
    """One row per Excel column. Seeded from app/fields/fields_v1.json."""

    __tablename__ = "field_definitions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)  # exact Excel header
    excel_column: Mapped[str] = mapped_column(String(4), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    field_type: Mapped[FieldType] = mapped_column(_enum(FieldType), nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(String(16))
    section_key: Mapped[str] = mapped_column(String(64), nullable=False)
    section_label: Mapped[str] = mapped_column(String(120), nullable=False)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    counts_toward_progress: Mapped[bool] = mapped_column(Boolean, nullable=False)
    system_source: Mapped[str | None] = mapped_column(String(32))
    zoho_api_name: Mapped[str | None] = mapped_column(String(100))  # mapped in the Zoho phase
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# --- 3. customers --------------------------------------------------------------

customer_ref_seq = Sequence("customer_ref_seq", start=1)


class Customer(Timestamped, Base):
    """A prospect / lead and the latest known value of every field."""

    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_zoho_due", "zoho_sync_status", "zoho_next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ref_no: Mapped[int] = mapped_column(
        BigInteger, customer_ref_seq, server_default=customer_ref_seq.next_value(), unique=True, nullable=False
    )
    owner_staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"), nullable=False, index=True)
    # Digits-only copy of the Mobile field, used for the duplicate check.
    mobile_normalized: Mapped[str | None] = mapped_column(String(15), index=True)

    # Current state: {field_key: value} for every field collected so far.
    current_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fields_filled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meeting_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_meeting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Lead conversion.
    conversion_status: Mapped[ConversionStatus] = mapped_column(
        _enum(ConversionStatus), nullable=False, default=ConversionStatus.NOT_CONVERTED, index=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))

    # Zoho Lead sync (only used once conversion starts).
    zoho_lead_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # The Zoho Lead form exactly as the staff member confirmed it ({zoho_api_name: value}).
    # The sync sends this when creating the Lead; if empty it builds a default one.
    zoho_lead_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    zoho_sync_status: Mapped[SyncStatus] = mapped_column(
        _enum(SyncStatus), nullable=False, default=SyncStatus.NOT_QUEUED
    )
    zoho_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zoho_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    zoho_last_error: Mapped[str | None] = mapped_column(Text)

    owner: Mapped[Staff] = relationship(foreign_keys=[owner_staff_id])

    @property
    def lead_ref(self) -> str:
        return f"MSME-{self.ref_no:04d}"


# --- 4. meetings ---------------------------------------------------------------


class Meeting(Timestamped, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("customer_id", "sequence_no"),
        Index("ix_meetings_zoho_due", "zoho_sync_status", "zoho_next_attempt_at"),
    )

    # Generated on the phone so a retried upload can never create a second meeting.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MeetingStatus] = mapped_column(_enum(MeetingStatus), nullable=False, default=MeetingStatus.DRAFT)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # History: [{"field", "old", "new", "type": "NEW"|"UPDATED"}], fixed once completed.
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # GPS at meeting start and end.
    gps_status: Mapped[GpsStatus] = mapped_column(_enum(GpsStatus), nullable=False, default=GpsStatus.PENDING)
    gps_unavailable_reason: Mapped[str | None] = mapped_column(Text)
    # Readable place worked out from the start GPS (e.g. "Shanthi Colony, Anna Nagar, Chennai").
    # Belongs to THIS meeting only; the lead's own Location field is never changed by it.
    start_place: Mapped[str | None] = mapped_column(Text)
    place_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    start_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    start_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    start_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # device clock
    end_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    end_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    end_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    end_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Zoho Meeting sync.
    zoho_meeting_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    zoho_sync_status: Mapped[SyncStatus] = mapped_column(
        _enum(SyncStatus), nullable=False, default=SyncStatus.NOT_QUEUED
    )
    zoho_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zoho_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    zoho_last_error: Mapped[str | None] = mapped_column(Text)


# --- 5. audit_log ----------------------------------------------------------------


class AuditLog(Base):
    """Who did what. Also records every Zoho sync attempt (action ZOHO_SYNC_*)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
