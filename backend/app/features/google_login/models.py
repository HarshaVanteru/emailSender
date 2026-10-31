from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, select, func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from app.core.database import Base
from app.core.sql_types import ID_TYPE


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("user_id", "id", name="uq_accounts_user_id"),)
    id = Column(ID_TYPE, primary_key=True)
    user_id = Column(ID_TYPE, ForeignKey("users.id"), nullable=False, index=True)
    gmail_email = Column(String(255), nullable=False, unique=True)
    google_sub = Column(String(255), nullable=True, unique=True, index=True)
    initial_sync_days = Column(Integer, nullable=False, default=30, server_default="30")
    repair_after_id = Column(ID_TYPE, nullable=True)
    legacy_credentials = Column("encrypted_credentials", Text, nullable=True)
    credential = relationship("OAuthCredential", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    scopes = Column(Text, nullable=False, default="[]")
    # A profile snapshot is NOT a committed synchronization cursor.
    profile_history_id = Column(String(255), nullable=True)
    history_id = Column(String(255), nullable=True)
    mail_import_complete = Column(Boolean, nullable=False, default=False, server_default="0")
    mail_import_page_token = Column(Text, nullable=True)
    mail_import_history_id = Column(String(255), nullable=True)
    mail_import_started_at = Column(DateTime, nullable=True)
    mail_import_seen_tokens = Column(JSON, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    next_sync_at = Column(DateTime, nullable=True, index=True)
    next_reconcile_at = Column(DateTime, nullable=True)
    sync_paused = Column(Boolean, nullable=False, default=False, server_default="0")
    watch_expiration = Column(DateTime, nullable=True)
    next_watch_attempt_at = Column(DateTime, nullable=True, index=True)
    watch_last_error_code = Column(String(128), nullable=True)
    requires_reauth = Column(Boolean, nullable=False, default=False)

    @hybrid_property
    def encrypted_credentials(self):
        return self.credential.encrypted_payload if self.credential else self.legacy_credentials

    @encrypted_credentials.setter
    def encrypted_credentials(self, value):
        from app.core.config import TOKEN_ENCRYPTION_KEY_VERSION
        if self.credential is None and value is not None:
            self.credential = OAuthCredential(encrypted_payload=value, encryption_key_version=TOKEN_ENCRYPTION_KEY_VERSION)
        elif self.credential is not None:
            self.credential.encrypted_payload = value
            self.credential.encryption_key_version = TOKEN_ENCRYPTION_KEY_VERSION
        self.legacy_credentials = None

    @encrypted_credentials.expression
    def encrypted_credentials(cls):
        current = select(OAuthCredential.encrypted_payload).where(OAuthCredential.account_id == cls.id).scalar_subquery()
        return func.coalesce(current, cls.legacy_credentials)


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    account_id = Column(ID_TYPE, ForeignKey("connected_accounts.id"), primary_key=True)
    encrypted_payload = Column(Text)
    encryption_key_version = Column(String(50), nullable=False)


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"
    state_hash = Column(String(64), primary_key=True)
    browser_hash = Column(String(64), nullable=False)
    encrypted_verifier = Column(Text, nullable=False)
    requested_scopes = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    user_id = Column(ID_TYPE, ForeignKey("users.id"), nullable=True)
    session_id = Column(String(64), nullable=True)
    account_id = Column(ID_TYPE, ForeignKey("connected_accounts.id"), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(String(64), primary_key=True)
    user_id = Column(ID_TYPE, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)


class LoginIdentity(Base):
    __tablename__ = "login_identities"
    google_sub = Column(String(255), primary_key=True)
    user_id = Column(ID_TYPE, ForeignKey("users.id"), nullable=False, index=True)
