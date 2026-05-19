"""phase_1_customer_layer_and_policy_lifecycle

Revision ID: e3fada8b937e
Revises: f6f188f8df82
Create Date: 2026-04-30 05:22:13.598551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3fada8b937e'
down_revision: Union[str, Sequence[str], None] = 'f6f188f8df82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "customers" not in tables:
        op.create_table(
            "customers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sa.String(), nullable=False),
            sa.Column("primary_email", sa.String(), nullable=True),
            sa.Column("primary_phone", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "customer_entities" not in tables:
        op.create_table(
            "customer_entities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("entity_name", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("first_seen", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "policy_relationships" not in tables:
        op.create_table(
            "policy_relationships",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("policy_id", sa.Integer(), nullable=True),
            sa.Column("related_policy_id", sa.Integer(), nullable=True),
            sa.Column("relationship_type", sa.String(), nullable=True),
            sa.Column("confidence", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["policy_id"], ["policies.id"]),
            sa.ForeignKeyConstraint(["related_policy_id"], ["policies.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    policy_columns = {col["name"] for col in inspector.get_columns("policies")}
    with op.batch_alter_table("policies", schema=None) as batch_op:
        if "customer_id" not in policy_columns:
            batch_op.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        if "policy_status" not in policy_columns:
            batch_op.add_column(sa.Column("policy_status", sa.String(), nullable=True))
        if "replaced_by_policy_id" not in policy_columns:
            batch_op.add_column(sa.Column("replaced_by_policy_id", sa.Integer(), nullable=True))
        if "field_confidences" not in policy_columns:
            batch_op.add_column(sa.Column("field_confidences", sa.JSON(), nullable=True))
        if "document_type" not in policy_columns:
            batch_op.add_column(sa.Column("document_type", sa.String(), nullable=True))
        if "layout_fingerprint" not in policy_columns:
            batch_op.add_column(sa.Column("layout_fingerprint", sa.String(), nullable=True))

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("policies") if fk.get("name")}
    with op.batch_alter_table("policies", schema=None) as batch_op:
        if "fk_policies_customer_id_customers" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_policies_customer_id_customers", "customers", ["customer_id"], ["id"]
            )
        if "fk_policies_replaced_by_policy_id_policies" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_policies_replaced_by_policy_id_policies",
                "policies",
                ["replaced_by_policy_id"],
                ["id"],
            )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    policy_columns = {col["name"] for col in inspector.get_columns("policies")}
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("policies") if fk.get("name")}
    with op.batch_alter_table("policies", schema=None) as batch_op:
        if "fk_policies_replaced_by_policy_id_policies" in foreign_keys:
            batch_op.drop_constraint("fk_policies_replaced_by_policy_id_policies", type_="foreignkey")
        if "fk_policies_customer_id_customers" in foreign_keys:
            batch_op.drop_constraint("fk_policies_customer_id_customers", type_="foreignkey")
        if "layout_fingerprint" in policy_columns:
            batch_op.drop_column("layout_fingerprint")
        if "document_type" in policy_columns:
            batch_op.drop_column("document_type")
        if "field_confidences" in policy_columns:
            batch_op.drop_column("field_confidences")
        if "replaced_by_policy_id" in policy_columns:
            batch_op.drop_column("replaced_by_policy_id")
        if "policy_status" in policy_columns:
            batch_op.drop_column("policy_status")
        if "customer_id" in policy_columns:
            batch_op.drop_column("customer_id")

    tables = set(inspector.get_table_names())
    if "policy_relationships" in tables:
        op.drop_table("policy_relationships")
    if "customer_entities" in tables:
        op.drop_table("customer_entities")
    if "customers" in tables:
        op.drop_table("customers")
