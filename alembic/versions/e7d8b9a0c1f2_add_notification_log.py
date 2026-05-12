"""add notification_log table

Revision ID: e7d8b9a0c1f2
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11 21:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7d8b9a0c1f2"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: skip if the table already exists (defensive against partial
    # migrations on long-running dev DBs).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notification_log" in inspector.get_table_names():
        return

    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("policies.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("contacted_at", sa.DateTime(), nullable=False),
        sa.Column(
            "method",
            sa.String(),
            nullable=False,
            server_default="email_draft",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notification_log" not in inspector.get_table_names():
        return
    op.drop_table("notification_log")
