"""endorsements and premium audit

Revision ID: 2d4f7b2bc1de
Revises: e3fada8b937e
Create Date: 2026-04-30 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d4f7b2bc1de"
down_revision: Union[str, None] = "e3fada8b937e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "policy_endorsements" not in tables:
        op.create_table(
            "policy_endorsements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("parent_policy_id", sa.Integer(), sa.ForeignKey("policies.id"), nullable=True),
            sa.Column("parent_policy_number", sa.String(), nullable=True),
            sa.Column("endorsement_type", sa.String(), nullable=True),
            sa.Column("endorsement_form_number", sa.String(), nullable=True),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("changes_summary", sa.Text(), nullable=True),
            sa.Column("file_hash", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "policy_endorsements" in tables:
        op.drop_table("policy_endorsements")
