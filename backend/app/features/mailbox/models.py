"""Account-scoped Gmail cache. Gmail remains authoritative for message state.

Dates are naive UTC except internal_date/last_message_at, which retain Gmail's
epoch milliseconds. HTML is untrusted source content, never safe to render as-is.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.mysql import LONGTEXT

from app.core.database import Base

LARGE_TEXT = Text().with_variant(LONGTEXT(), "mysql")
# Binary collation preserves case-sensitive provider IDs on MySQL.
MYSQL_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


class EmailThread(Base):
    __tablename__ = "email_threads"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_thread_id", name="uq_threads_gmail_id"),
        UniqueConstraint("account_id", "id", name="uq_threads_account_id"),
        Index("ix_threads_account_date", "account_id", "last_message_at"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("connected_accounts.id"), nullable=False)
    gmail_thread_id = Column(String(128), nullable=False)
    subject = Column(Text)
    snippet = Column(Text)
    last_message_at = Column(BigInteger)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_message_id", name="uq_messages_gmail_id"),
        UniqueConstraint("account_id", "id", name="uq_messages_account_id"),
        ForeignKeyConstraint(["account_id", "thread_id"], ["email_threads.account_id", "email_threads.id"],
                             name="fk_messages_account_thread", ondelete="CASCADE"),
        Index("ix_messages_account_date", "account_id", "internal_date"),
        Index("ix_messages_thread_date", "account_id", "thread_id", "internal_date"),
        CheckConstraint("size_estimate >= 0", name="ck_messages_size"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("connected_accounts.id"), nullable=False)
    thread_id = Column(Integer, nullable=False)
    gmail_message_id = Column(String(128), nullable=False)
    gmail_history_id = Column(String(255))
    from_address = Column(Text)
    to_addresses = Column(JSON, nullable=False, default=list)
    cc_addresses = Column(JSON, nullable=False, default=list)
    bcc_addresses = Column(JSON, nullable=False, default=list)
    subject = Column(Text)
    snippet = Column(Text)
    # Ordered name/value pairs preserve repeated RFC headers for later replies.
    headers = Column(JSON, nullable=False, default=list)
    body_text = Column(LARGE_TEXT)
    body_html = Column(LARGE_TEXT)
    internal_date = Column(BigInteger, nullable=False)
    size_estimate = Column(BigInteger, nullable=False, default=0, server_default="0")
    cached_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class EmailLabel(Base):
    __tablename__ = "email_labels"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_label_id", name="uq_labels_gmail_id"),
        UniqueConstraint("account_id", "id", name="uq_labels_account_id"),
        CheckConstraint("type IN ('system', 'user')", name="ck_labels_type"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("connected_accounts.id"), nullable=False)
    gmail_label_id = Column(String(128), nullable=False)
    name = Column(Text, nullable=False)
    type = Column(String(16), nullable=False)


class MessageLabel(Base):
    __tablename__ = "message_labels"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"],
                             name="fk_message_labels_account_message", ondelete="CASCADE"),
        ForeignKeyConstraint(["account_id", "label_id"], ["email_labels.account_id", "email_labels.id"],
                             name="fk_message_labels_account_label", ondelete="CASCADE"),
        Index("ix_message_labels_account_label", "account_id", "label_id", "message_id"),
        MYSQL_OPTIONS,
    )
    account_id = Column(Integer, primary_key=True)
    message_id = Column(Integer, primary_key=True)
    label_id = Column(Integer, primary_key=True)


class EmailAttachment(Base):
    __tablename__ = "email_attachments"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"],
                             name="fk_attachments_account_message", ondelete="CASCADE"),
        UniqueConstraint("account_id", "message_id", "mime_part_id", name="uq_attachments_part"),
        CheckConstraint("size_bytes >= 0", name="ck_attachments_size"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    mime_part_id = Column(String(128), nullable=False)
    gmail_attachment_id = Column(Text)  # Some MIME parts have inline data instead.
    filename = Column(Text, nullable=False)
    mime_type = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    content_id = Column(Text)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('initial', 'incremental', 'reconcile')", name="ck_sync_jobs_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_sync_jobs_status"),
        CheckConstraint("attempts >= 0", name="ck_sync_jobs_attempts"),
        CheckConstraint("active_account_id IS NULL OR (active_account_id = account_id AND status IN ('queued', 'running'))", name="ck_sync_jobs_active_account"),
        UniqueConstraint("active_account_id", name="uq_sync_jobs_active_account"),
        Index("ix_sync_jobs_account_status", "account_id", "status", "created_at"),
        Index("ix_sync_jobs_dispatch", "status", "available_at", "dispatch_after"),
        Index("ix_sync_jobs_lease", "status", "lease_expires_at"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("connected_accounts.id"), nullable=False)
    kind = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="queued", server_default="queued")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_code = Column(String(128))  # Sanitized code, not provider response/secrets.
    active_account_id = Column(Integer)
    available_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    dispatch_after = Column(DateTime)
    lease_token = Column(String(64))
    lease_expires_at = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "account_id"], ["connected_accounts.user_id", "connected_accounts.id"],
                             name="fk_audit_logs_owner_account"),
        Index("ix_audit_logs_user_date", "user_id", "created_at"),
        Index("ix_audit_logs_account_date", "account_id", "created_at"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64))
    resource_id = Column(String(255))
    outcome = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "account_id"], ["connected_accounts.user_id", "connected_accounts.id"],
                             name="fk_ai_suggestions_owner_account"),
        ForeignKeyConstraint(["account_id", "thread_id"], ["email_threads.account_id", "email_threads.id"],
                             name="fk_ai_suggestions_account_thread", ondelete="CASCADE"),
        Index("ix_ai_suggestions_owner_thread_date", "user_id", "account_id", "thread_id", "created_at"),
        MYSQL_OPTIONS,
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    account_id = Column(Integer, nullable=False)
    thread_id = Column(Integer, nullable=False)
    message_id = Column(Integer)
    operation = Column(String(24), nullable=False)
    input_hash = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class MessageTriage(Base):
    __tablename__ = "message_triage"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "message_id"], ["email_messages.account_id", "email_messages.id"], ondelete="CASCADE"),
        CheckConstraint("state IN ('processing', 'retry', 'succeeded', 'failed')", name="ck_triage_state"),
        CheckConstraint("importance IS NULL OR importance IN ('critical', 'high', 'normal', 'low')", name="ck_triage_importance"),
        Index("ix_triage_account_state", "account_id", "state"),
        MYSQL_OPTIONS,
    )
    message_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    is_spam = Column(Integer)
    importance = Column(String(16))
    category = Column(String(24))
    reason = Column(String(240))
    attempts = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(48))
    available_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
