"""add premium_audit_flag

Revision ID: b9a1c3d4e5f6
Revises: 4b8a6d2f1c30
Create Date: 2026-04-30 20:23:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9a1c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "4b8a6d2f1c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("premium_audit_flag", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.drop_column("premium_audit_flag")
