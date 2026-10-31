"""Recent-window imports and on-demand historical checkpoints; retain cached mail."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"


def upgrade():
    op.add_column("connected_accounts", sa.Column("initial_sync_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("connected_accounts", sa.Column("repair_after_id", sa.Integer()))
    # Stop in-progress full-mailbox scans without deleting already imported mail.
    op.execute(sa.text("UPDATE connected_accounts SET mail_import_page_token=NULL, mail_import_started_at=NULL, mail_import_seen_tokens=NULL, mail_import_history_id=NULL WHERE mail_import_complete=0"))
    op.create_table("sync_sessions",
        sa.Column("internal_id", sa.Integer(), primary_key=True),
        sa.Column("id", sa.String(64), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128)),
        sa.Column("before_epoch", sa.Integer(), nullable=False),
        sa.Column("page_token_ciphertext", sa.Text()),
        sa.Column("seen_tokens", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("messages_imported", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.UniqueConstraint("account_id", "scope_key", name="uq_history_scope"))
    op.create_index("ix_sync_sessions_status", "sync_sessions", ["status"])


def downgrade():
    op.drop_table("sync_sessions")
    op.drop_column("connected_accounts", "repair_after_id")
    op.drop_column("connected_accounts", "initial_sync_days")
