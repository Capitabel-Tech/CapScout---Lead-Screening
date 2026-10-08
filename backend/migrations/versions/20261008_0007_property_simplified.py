"""property value and mortgage removed; property documents get Unknown

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op

from app.fields.seed import sync_catalog

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Labels, options and the field list come from fields_v1.json; removed fields are switched off.
    sync_catalog(op.get_bind())


def downgrade() -> None:
    pass
