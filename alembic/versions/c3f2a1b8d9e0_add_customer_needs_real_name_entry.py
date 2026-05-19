"""add customer needs_real_name_entry

Revision ID: c3f2a1b8d9e0
Revises: b9a1c3d4e5f6
Create Date: 2026-04-30 20:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f2a1b8d9e0"
down_revision: Union[str, Sequence[str], None] = "b9a1c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("needs_real_name_entry", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.drop_column("needs_real_name_entry")
