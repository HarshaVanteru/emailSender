"""Durable workflow records. Payloads are encrypted; Redis carries only IDs."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.sql_types import ID_TYPE


class OperationFields:
    internal_id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    id: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("connected_accounts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(150))
    input_hash: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), index=True)
    payload_ciphertext: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    result: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SendJob(OperationFields, Base):
    __tablename__ = "email_send_jobs"
    __table_args__ = (UniqueConstraint("account_id", "idempotency_key", name="uq_send_idempotency"),)
    rfc_message_id: Mapped[str | None] = mapped_column(String(255))


class AiJob(OperationFields, Base):
    __tablename__ = "ai_processing_jobs"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_ai_idempotency"),)
    account_id: Mapped[int | None] = mapped_column(ID_TYPE, ForeignKey("connected_accounts.id"))
    thread_id: Mapped[int] = mapped_column(ID_TYPE)
