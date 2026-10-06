"""initial schema (5 tables)

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.fields.seed import sync_catalog

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["staff", "field_definitions", "customers", "meetings", "audit_log"]

SYNC_STATUSES = ("NOT_QUEUED", "PENDING", "SYNCING", "SYNCED", "FAILED")


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _zoho_sync_columns() -> list[sa.Column]:
    return [
        sa.Column("zoho_sync_status", _enum("ck_syncstatus", *SYNC_STATUSES), nullable=False),
        sa.Column("zoho_attempts", sa.Integer(), nullable=False),
        sa.Column("zoho_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zoho_last_error", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "staff",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("employee_code", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("role", _enum("ck_staffrole", "FIELD_STAFF", "SUPERVISOR", "ADMIN"), nullable=False),
        sa.Column("zoho_user_id", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "field_definitions",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("excel_column", sa.String(4), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, unique=True),
        sa.Column(
            "field_type",
            _enum("ck_fieldtype", "system", "text", "long_text", "phone", "number", "date", "single_select"),
            nullable=False,
        ),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("section_key", sa.String(64), nullable=False),
        sa.Column("section_label", sa.String(120), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("counts_toward_progress", sa.Boolean(), nullable=False),
        sa.Column("system_source", sa.String(32), nullable=True),
        sa.Column("zoho_api_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )

    op.execute("CREATE SEQUENCE customer_ref_seq START 1")
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "ref_no", sa.BigInteger(), server_default=sa.text("nextval('customer_ref_seq')"), nullable=False, unique=True
        ),
        sa.Column("owner_staff_id", sa.UUID(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("mobile_normalized", sa.String(15), nullable=True),
        sa.Column("current_values", postgresql.JSONB(), nullable=False),
        sa.Column("fields_filled_count", sa.Integer(), nullable=False),
        sa.Column("meeting_count", sa.Integer(), nullable=False),
        sa.Column("last_meeting_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "conversion_status",
            _enum("ck_conversionstatus", "NOT_CONVERTED", "CONVERTING", "CONVERTED", "CONVERSION_FAILED"),
            nullable=False,
        ),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_by_staff_id", sa.UUID(), sa.ForeignKey("staff.id"), nullable=True),
        sa.Column("zoho_lead_id", sa.String(64), nullable=True, unique=True),
        *_zoho_sync_columns(),
        *_timestamps(),
    )
    op.create_index("ix_customers_owner_staff_id", "customers", ["owner_staff_id"])
    op.create_index("ix_customers_mobile_normalized", "customers", ["mobile_normalized"])
    op.create_index("ix_customers_conversion_status", "customers", ["conversion_status"])
    op.create_index("ix_customers_zoho_due", "customers", ["zoho_sync_status", "zoho_next_attempt_at"])
    op.execute("ALTER SEQUENCE customer_ref_seq OWNED BY customers.ref_no")

    op.create_table(
        "meetings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("staff_id", sa.UUID(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("status", _enum("ck_meetingstatus", "DRAFT", "COMPLETED"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("gps_status", _enum("ck_gpsstatus", "PENDING", "CAPTURED", "UNAVAILABLE"), nullable=False),
        sa.Column("gps_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("start_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("start_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("start_accuracy_m", sa.Numeric(8, 1), nullable=True),
        sa.Column("start_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("end_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("end_accuracy_m", sa.Numeric(8, 1), nullable=True),
        sa.Column("end_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zoho_meeting_id", sa.String(64), nullable=True, unique=True),
        *_zoho_sync_columns(),
        *_timestamps(),
        sa.UniqueConstraint("customer_id", "sequence_no"),
    )
    op.create_index("ix_meetings_customer_id", "meetings", ["customer_id"])
    op.create_index("ix_meetings_staff_id", "meetings", ["staff_id"])
    op.create_index("ix_meetings_zoho_due", "meetings", ["zoho_sync_status", "zoho_next_attempt_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("staff_id", sa.UUID(), sa.ForeignKey("staff.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_log_staff_id", "audit_log", ["staff_id"])

    # Supabase exposes the public schema through its Data API. RLS with no
    # policies shuts that path; all access goes through the FastAPI backend.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    sync_catalog(op.get_bind())


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
