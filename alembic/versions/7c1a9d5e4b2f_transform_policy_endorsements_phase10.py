"""transform policy_endorsements to phase 10 schema

Revision ID: 7c1a9d5e4b2f
Revises: 2d4f7b2bc1de
Create Date: 2026-04-30 11:27:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1a9d5e4b2f"
down_revision: Union[str, None] = "2d4f7b2bc1de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("policy_endorsements")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "policy_endorsements" not in inspector.get_table_names():
        return

    columns = _column_names(inspector)

    with op.batch_alter_table("policy_endorsements", schema=None) as batch_op:
        if "policy_id" in columns and "parent_policy_id" not in columns:
            batch_op.alter_column("policy_id", new_column_name="parent_policy_id")

        if "parent_policy_number" not in columns:
            batch_op.add_column(sa.Column("parent_policy_number", sa.String(), nullable=True))
        if "endorsement_type" not in columns:
            batch_op.add_column(sa.Column("endorsement_type", sa.String(), nullable=True))
        if "endorsement_form_number" not in columns:
            batch_op.add_column(sa.Column("endorsement_form_number", sa.String(), nullable=True))
        if "changes_summary" not in columns:
            batch_op.add_column(sa.Column("changes_summary", sa.Text(), nullable=True))
        if "file_hash" not in columns:
            batch_op.add_column(sa.Column("file_hash", sa.String(), nullable=True))
        if "created_at" not in columns:
            batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))

        if "source_document_type" in columns:
            batch_op.drop_column("source_document_type")

    # Refresh column info after structural changes.
    inspector = sa.inspect(bind)
    columns = _column_names(inspector)

    if "description" in columns and "changes_summary" in columns:
        op.execute(
            sa.text(
                """
                UPDATE policy_endorsements
                SET changes_summary = description
                WHERE (changes_summary IS NULL OR TRIM(changes_summary) = '')
                  AND description IS NOT NULL
                  AND TRIM(description) <> ''
                """
            )
        )

    if "form_id" in columns and "endorsement_form_number" in columns:
        op.execute(
            sa.text(
                """
                UPDATE policy_endorsements
                SET endorsement_form_number = form_id
                WHERE (endorsement_form_number IS NULL OR TRIM(endorsement_form_number) = '')
                  AND form_id IS NOT NULL
                  AND TRIM(form_id) <> ''
                """
            )
        )

    if "endorsement_type" in columns:
        op.execute(
            sa.text(
                """
                UPDATE policy_endorsements
                SET endorsement_type = 'other'
                WHERE endorsement_type IS NULL OR TRIM(endorsement_type) = ''
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "policy_endorsements" not in inspector.get_table_names():
        return

    columns = _column_names(inspector)
    with op.batch_alter_table("policy_endorsements", schema=None) as batch_op:
        if "source_document_type" not in columns:
            batch_op.add_column(sa.Column("source_document_type", sa.String(), nullable=True))
        if "parent_policy_id" in columns and "policy_id" not in columns:
            batch_op.alter_column("parent_policy_id", new_column_name="policy_id")
