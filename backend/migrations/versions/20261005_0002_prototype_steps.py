"""regroup fields into the prototype's 6 steps

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op

from app.fields.seed import sync_catalog

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Field labels and options are unchanged (still the Excel); only the
    # step each field appears in, and its order there, change.
    sync_catalog(op.get_bind())


def downgrade() -> None:
    pass
