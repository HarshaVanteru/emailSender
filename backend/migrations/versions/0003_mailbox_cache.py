"""Account-isolated mailbox cache, synchronization cursor/jobs, and audit records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0003"
down_revision = "0002"

MYSQL_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


def upgrade():
    with op.batch_alter_table("connected_accounts") as batch:
        batch.add_column(sa.Column("history_id", sa.String(255)))
        batch.add_column(sa.Column("last_synced_at", sa.DateTime()))
        batch.add_column(sa.Column("watch_expiration", sa.DateTime()))
        batch.create_unique_constraint("uq_accounts_user_id", ["user_id", "id"])

    op.create_table("email_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=False),
        sa.Column("gmail_thread_id", sa.String(128), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("snippet", sa.Text()),
        sa.Column("last_message_at", sa.BigInteger()),
        sa.UniqueConstraint("account_id", "gmail_thread_id", name="uq_threads_gmail_id"),
        sa.UniqueConstraint("account_id", "id", name="uq_threads_account_id"),
        **MYSQL_OPTIONS,
    )
    op.create_index("ix_threads_account_date", "email_threads", ["account_id", "last_message_at"])

    op.create_table("email_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("gmail_message_id", sa.String(128), nullable=False),
        sa.Column("gmail_history_id", sa.String(255)),
        sa.Column("from_address", sa.Text()),
        sa.Column("to_addresses", sa.JSON(), nullable=False),
        sa.Column("cc_addresses", sa.JSON(), nullable=False),
        sa.Column("bcc_addresses", sa.JSON(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("snippet", sa.Text()),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body_text", sa.Text().with_variant(LONGTEXT(), "mysql")),
        sa.Column("body_html", sa.Text().with_variant(LONGTEXT(), "mysql")),
        sa.Column("internal_date", sa.BigInteger(), nullable=False),
        sa.Column("size_estimate", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cached_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("account_id", "gmail_message_id", name="uq_messages_gmail_id"),
        sa.UniqueConstraint("account_id", "id", name="uq_messages_account_id"),
        sa.ForeignKeyConstraint(["account_id", "thread_id"], ["email_threads.account_id", "email_threads.id"],
                                name="fk_messages_account_thread", ondelete="CASCADE"),
        sa.CheckConstraint("size_estimate >= 0", name="ck_messages_size"),
        **MYSQL_OPTIONS,
    )
    op.create_index("ix_messages_account_date", "email_messages", ["account_id", "internal_date"])
    op.create_index("ix_messages_thread_date", "email_messages", ["account_id", "thread_id", "internal_date"])

    op.create_table("email_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=False),
        sa.Column("gmail_label_id", sa.String(128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.UniqueConstraint("account_id", "gmail_label_id", name="uq_labels_gmail_id"),
        sa.UniqueConstraint("account_id", "id", name="uq_labels_account_id"),
        sa.CheckConstraint("type IN ('system', 'user')", name="ck_labels_type"),
        **MYSQL_OPTIONS,
    )

    op.create_table("message_labels",
        sa.Column("account_id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), primary_key=True),
        sa.Column("label_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"],
                                name="fk_message_labels_account_message", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id", "label_id"], ["email_labels.account_id", "email_labels.id"],
                                name="fk_message_labels_account_label", ondelete="CASCADE"),
        **MYSQL_OPTIONS,
    )
    op.create_index("ix_message_labels_account_label", "message_labels", ["account_id", "label_id", "message_id"])

    op.create_table("email_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("mime_part_id", sa.String(128), nullable=False),
        sa.Column("gmail_attachment_id", sa.Text()),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_id", sa.Text()),
        sa.ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"],
                                name="fk_attachments_account_message", ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "message_id", "mime_part_id", name="uq_attachments_part"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_attachments_size"),
        **MYSQL_OPTIONS,
    )

    op.create_table("sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("error_code", sa.String(128)),
        sa.CheckConstraint("kind IN ('initial', 'incremental', 'reconcile')", name="ck_sync_jobs_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_sync_jobs_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_sync_jobs_attempts"),
        **MYSQL_OPTIONS,
    )
    op.create_index("ix_sync_jobs_account_status", "sync_jobs", ["account_id", "status", "created_at"])

    op.create_table("audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["user_id", "account_id"], ["connected_accounts.user_id", "connected_accounts.id"],
                                name="fk_audit_logs_owner_account"),
        **MYSQL_OPTIONS,
    )
    op.create_index("ix_audit_logs_user_date", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_account_date", "audit_logs", ["account_id", "created_at"])


def downgrade():
    # Only cached content/operational records are removed. Credentials and writing
    # preferences remain intact at 0002; nothing calls Gmail or deletes remote mail.
    for table in ("audit_logs", "sync_jobs", "email_attachments", "message_labels",
                  "email_labels", "email_messages", "email_threads"):
        op.drop_table(table)
    with op.batch_alter_table("connected_accounts") as batch:
        batch.drop_constraint("uq_accounts_user_id", type_="unique")
        batch.drop_column("watch_expiration")
        batch.drop_column("last_synced_at")
        batch.drop_column("history_id")
