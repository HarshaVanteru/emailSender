"""Durable user-requested historical pages; provider tokens never leave storage."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.core.database import Base
from app.core.sql_types import ID_TYPE


class HistorySession(Base):
    __tablename__ = "sync_sessions"
    __table_args__ = (UniqueConstraint("account_id", "scope_key", name="uq_history_scope"),)
    internal_id = Column(ID_TYPE, primary_key=True)
    id = Column(String(64), nullable=False, unique=True)
    account_id = Column(ID_TYPE, ForeignKey("connected_accounts.id"), nullable=False)
    user_id = Column(ID_TYPE, ForeignKey("users.id"), nullable=False)
    scope_key = Column(String(64), nullable=False)
    label = Column(String(128))
    before_epoch = Column(Integer, nullable=False)
    page_token_ciphertext = Column(Text)
    seen_tokens = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    messages_imported = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    error_code = Column(String(128))
