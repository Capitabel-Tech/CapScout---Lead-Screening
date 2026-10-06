"""readable place for each meeting, worked out from its GPS

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("start_place", sa.Text(), nullable=True))
    op.add_column("meetings", sa.Column("place_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("meetings", "place_attempts")
    op.drop_column("meetings", "start_place")
