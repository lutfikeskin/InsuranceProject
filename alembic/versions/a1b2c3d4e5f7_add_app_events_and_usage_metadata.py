"""add app events and usage metadata

Revision ID: a1b2c3d4e5f7
Revises: d4e5f6a7b8c9
Create Date: 2026-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_usage", sa.Column("correlation_id", sa.String(), nullable=True))
    op.add_column("api_usage", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("api_usage", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.create_index("ix_api_usage_correlation_id", "api_usage", ["correlation_id"], unique=False)
    op.create_index("ix_api_usage_status", "api_usage", ["status"], unique=False)
    op.create_index("ix_api_usage_request_type", "api_usage", ["request_type"], unique=False)
    op.create_index("ix_api_usage_timestamp", "api_usage", ["timestamp"], unique=False)

    op.create_table(
        "app_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("object_id", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("count_value", sa.Integer(), nullable=True),
        sa.Column("value_float", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_app_events_timestamp", "app_events", ["timestamp"], unique=False)
    op.create_index("ix_app_events_event_name", "app_events", ["event_name"], unique=False)
    op.create_index("ix_app_events_category", "app_events", ["category"], unique=False)
    op.create_index("ix_app_events_status", "app_events", ["status"], unique=False)
    op.create_index("ix_app_events_correlation_id", "app_events", ["correlation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_app_events_correlation_id", table_name="app_events")
    op.drop_index("ix_app_events_status", table_name="app_events")
    op.drop_index("ix_app_events_category", table_name="app_events")
    op.drop_index("ix_app_events_event_name", table_name="app_events")
    op.drop_index("ix_app_events_timestamp", table_name="app_events")
    op.drop_table("app_events")

    op.drop_index("ix_api_usage_timestamp", table_name="api_usage")
    op.drop_index("ix_api_usage_request_type", table_name="api_usage")
    op.drop_index("ix_api_usage_status", table_name="api_usage")
    op.drop_index("ix_api_usage_correlation_id", table_name="api_usage")
    op.drop_column("api_usage", "latency_ms")
    op.drop_column("api_usage", "error_message")
    op.drop_column("api_usage", "correlation_id")
