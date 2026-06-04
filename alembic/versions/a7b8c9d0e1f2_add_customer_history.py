"""add customer history table and customers.updated_at

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-05-21 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    cols = {c["name"] for c in inspector.get_columns(table_name)}
    return column_name in cols


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "customers") and not _column_exists(inspector, "customers", "updated_at"):
        with op.batch_alter_table("customers") as batch_op:
            batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    if not _table_exists(inspector, "customer_history"):
        op.create_table(
            "customer_history",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "customer_id",
                sa.Integer(),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("customer_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("changes", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_customer_history_customer_id_timestamp",
            "customer_history",
            ["customer_id", "timestamp"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "customer_history"):
        try:
            op.drop_index("ix_customer_history_customer_id_timestamp", table_name="customer_history")
        except Exception:
            pass
        op.drop_table("customer_history")

    if _table_exists(inspector, "customers") and _column_exists(inspector, "customers", "updated_at"):
        with op.batch_alter_table("customers") as batch_op:
            batch_op.drop_column("updated_at")
