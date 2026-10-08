"""Litigation/Dispute after the documents

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op

from app.fields.seed import sync_catalog

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Labels, options and the field list come from fields_v1.json; removed fields are switched off.
    sync_catalog(op.get_bind())


def downgrade() -> None:
    pass
