"""store the confirmed Zoho Lead form on the customer

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("zoho_lead_payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "zoho_lead_payload")
