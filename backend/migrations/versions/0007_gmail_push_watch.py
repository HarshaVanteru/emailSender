"""Schedule Gmail watch renewals independently of mailbox sync."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"


def upgrade():
    op.add_column("connected_accounts", sa.Column("next_watch_attempt_at", sa.DateTime(), nullable=True))
    op.create_index("ix_connected_accounts_next_watch_attempt_at", "connected_accounts", ["next_watch_attempt_at"])


def downgrade():
    op.drop_index("ix_connected_accounts_next_watch_attempt_at", table_name="connected_accounts")
    op.drop_column("connected_accounts", "next_watch_attempt_at")
