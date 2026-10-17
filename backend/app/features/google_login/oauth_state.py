import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import GMAIL_LEGACY_SCOPES, GMAIL_SCOPES, OAUTH_STATE_TTL_SECONDS
from app.core.token_crypto import decrypt, encrypt
from app.features.google_login.models import OAuthAttempt


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_name(state: str) -> str:
    return "gmail_oauth_" + digest(state)[:24]


@dataclass(frozen=True)
class OAuthAttemptData:
    verifier: str
    scopes: list[str]


def create_attempt(db: Session, scopes=None):
    state, browser, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    encrypted = encrypt(verifier)  # Fail closed before persisting anything.
    db.query(OAuthAttempt).filter(OAuthAttempt.expires_at <= now()).delete()
    db.add(OAuthAttempt(
        state_hash=digest(state), browser_hash=digest(browser),
        encrypted_verifier=encrypted,
        requested_scopes=json.dumps(scopes or GMAIL_SCOPES),
        expires_at=now() + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    ))
    db.commit()
    return state, browser, verifier


def consume_attempt(db: Session, state: str, browser: str | None) -> OAuthAttemptData:
    if not browser or len(state) > 256:
        raise ValueError("Invalid or expired OAuth state")
    query = db.query(OAuthAttempt).filter(
        OAuthAttempt.state_hash == digest(state),
        OAuthAttempt.browser_hash == digest(browser),
        OAuthAttempt.expires_at > now(),
    )
    attempt = query.first()
    if not attempt:
        raise ValueError("Invalid or expired OAuth state")
    encrypted = attempt.encrypted_verifier
    # Older attempts without saved scopes requested send-only access. Preserve
    # that original request even though new logins now request gmail.modify.
    scopes = json.loads(attempt.requested_scopes or "[]") or GMAIL_LEGACY_SCOPES
    # Atomic conditional deletion prevents two workers redeeming the same state.
    removed = query.delete(synchronize_session=False)
    db.commit()
    if removed != 1:
        raise ValueError("Invalid or expired OAuth state")
    return OAuthAttemptData(decrypt(encrypted), scopes)
