"""add underwriter_name to policy

Revision ID: d4e5f6a7b8c9
Revises: c3f2a1b8d9e0
Create Date: 2026-04-30 16:58:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3f2a1b8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    policy_columns = {col["name"] for col in inspector.get_columns("policies")}
    if "underwriter_name" in policy_columns:
        return
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("underwriter_name", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    policy_columns = {col["name"] for col in inspector.get_columns("policies")}
    if "underwriter_name" not in policy_columns:
        return
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.drop_column("underwriter_name")
