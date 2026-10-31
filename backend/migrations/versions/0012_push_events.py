"""Durable authenticated push event inbox."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"


def upgrade():
    op.create_table("gmail_push_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id")),
        sa.Column("pubsub_message_id", sa.String(255), nullable=False, unique=True),
        sa.Column("history_id", sa.String(255), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime()),
        sa.Column("status", sa.String(24), nullable=False))
    op.create_index("ix_gmail_push_events_account_id", "gmail_push_events", ["account_id"])


def downgrade():
    op.drop_table("gmail_push_events")
