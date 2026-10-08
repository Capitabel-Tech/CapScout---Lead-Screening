"""client field changes: POC label, constitution/purpose options, turnover label, surplus removed

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op

from app.fields.seed import sync_catalog

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Labels, options and the field list come from fields_v1.json; removed fields are switched off.
    sync_catalog(op.get_bind())


def downgrade() -> None:
    pass
