from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("user_id", "id", name="uq_accounts_user_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    gmail_email = Column(String(255), nullable=False, unique=True)
    encrypted_credentials = Column(Text, nullable=True)
    scopes = Column(Text, nullable=False, default="[]")
    # A profile snapshot is NOT a committed synchronization cursor.
    profile_history_id = Column(String(255), nullable=True)
    history_id = Column(String(255), nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    next_sync_at = Column(DateTime, nullable=True, index=True)
    next_reconcile_at = Column(DateTime, nullable=True)
    sync_paused = Column(Boolean, nullable=False, default=False, server_default="0")
    watch_expiration = Column(DateTime, nullable=True)
    next_watch_attempt_at = Column(DateTime, nullable=True, index=True)
    requires_reauth = Column(Boolean, nullable=False, default=False)


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"
    state_hash = Column(String(64), primary_key=True)
    browser_hash = Column(String(64), nullable=False)
    encrypted_verifier = Column(Text, nullable=False)
    requested_scopes = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
