"""Baseline existing users schema. Stamp this revision for an existing database."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("google_token", sa.String(2048)),
        sa.Column("signature", sa.String(1024)),
        sa.Column("preferences", sa.String(2048)),
        sa.Column("bio", sa.Text()),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade():
    op.drop_table("users")
