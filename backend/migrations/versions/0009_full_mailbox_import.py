"""Resumable full-mailbox listing, including existing recent-only accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"


def upgrade():
    op.add_column("connected_accounts", sa.Column("mail_import_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("connected_accounts", sa.Column("mail_import_page_token", sa.Text(), nullable=True))
    op.add_column("connected_accounts", sa.Column("mail_import_history_id", sa.String(255), nullable=True))
    op.add_column("connected_accounts", sa.Column("mail_import_started_at", sa.DateTime(), nullable=True))
    op.add_column("connected_accounts", sa.Column("mail_import_seen_tokens", sa.JSON(), nullable=True))
    # Existing connections automatically backfill on the next maintenance pass.
    op.execute(sa.text("UPDATE connected_accounts SET next_sync_at = NULL WHERE sync_paused = 0"))


def downgrade():
    for column in ("mail_import_seen_tokens", "mail_import_started_at", "mail_import_history_id", "mail_import_page_token", "mail_import_complete"):
        op.drop_column("connected_accounts", column)
