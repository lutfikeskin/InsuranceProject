"""add durable review workflow tables

Revision ID: f1a2b3c4d5e6
Revises: e7d8b9a0c1f2
Create Date: 2026-05-19 14:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7d8b9a0c1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "uploaded_documents"):
        op.create_table(
            "uploaded_documents",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("file_hash", sa.String(), nullable=False, index=True),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=False, server_default="manual_upload"),
            sa.Column("storage_uri", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(inspector, "extraction_runs"):
        op.create_table(
            "extraction_runs",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "upload_id",
                sa.Integer(),
                sa.ForeignKey("uploaded_documents.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("policy_data_source", sa.String(), nullable=True),
            sa.Column("document_type", sa.String(), nullable=True),
            sa.Column("policy_type", sa.String(), nullable=True),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("cache_source", sa.String(), nullable=True),
            sa.Column("force_refresh", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("usage", sa.JSON(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(inspector, "review_tasks"):
        op.create_table(
            "review_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "upload_id",
                sa.Integer(),
                sa.ForeignKey("uploaded_documents.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "extraction_run_id",
                sa.Integer(),
                sa.ForeignKey("extraction_runs.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("decision", sa.String(), nullable=True),
            sa.Column("target_policy_id", sa.Integer(), sa.ForeignKey("policies.id"), nullable=True, index=True),
            sa.Column("extraction_result", sa.JSON(), nullable=False),
            sa.Column("human_edits", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ("review_tasks", "extraction_runs", "uploaded_documents"):
        if _table_exists(inspector, table_name):
            op.drop_table(table_name)
