"""Account-scoped Mybox classification records."""
from alembic import op
import sqlalchemy as sa
revision = "0008"
down_revision = "0007"


def upgrade():
    op.create_table("message_triage",
        sa.Column("message_id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("is_spam", sa.Integer()),
        sa.Column("importance", sa.String(16)),
        sa.Column("category", sa.String(24)),
        sa.Column("reason", sa.String(240)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(48)),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"], ondelete="CASCADE"),
        sa.CheckConstraint("state IN ('processing', 'retry', 'succeeded', 'failed')", name="ck_triage_state"),
        sa.CheckConstraint("importance IS NULL OR importance IN ('critical', 'high', 'normal', 'low')", name="ck_triage_importance"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_bin")
    op.create_index("ix_triage_account_state", "message_triage", ["account_id", "state"])


def downgrade():
    op.drop_table("message_triage")
