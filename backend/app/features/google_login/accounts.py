import json
from functools import partial

import requests
from fastapi import HTTPException
from cryptography.fernet import InvalidToken
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.core.token_crypto import decrypt, encrypt
from app.features.google_login.models import ConnectedAccount

PROFILE_SCOPES = {
    "https://mail.google.com/",
    *("https://www.googleapis.com/auth/gmail." + scope
      for scope in ("readonly", "modify", "metadata", "compose")),
}


class OfflineAccessRequired(HTTPException):
    def __init__(self):
        super().__init__(409, "Offline access is missing. Reconnect Gmail with renewed consent.")


def find_account(db: Session, user, lock=False):
    query = db.query(ConnectedAccount).filter(
        ConnectedAccount.user_id == user.id,
        ConnectedAccount.gmail_email == user.email,
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def save_connection(db: Session, user, credentials, profile_history_id=None):
    account = find_account(db, user, lock=True)
    data = json.loads(credentials.to_json())
    previous = None
    if account and account.encrypted_credentials:
        previous = json.loads(decrypt(account.encrypted_credentials))
    elif user.google_token:
        previous = json.loads(user.google_token)
    # Google often omits a refresh token on a subsequent authorization.
    if not data.get("refresh_token") and previous:
        data["refresh_token"] = previous.get("refresh_token")
    if not data.get("refresh_token"):
        raise OfflineAccessRequired()
    if not account:
        account = ConnectedAccount(user_id=user.id, gmail_email=user.email)
        db.add(account)
    account.encrypted_credentials = encrypt(json.dumps(data))
    account.scopes = json.dumps(list(credentials.granted_scopes or credentials.scopes or []))
    account.profile_history_id = profile_history_id
    account.requires_reauth = False
    account.sync_paused = False
    account.next_sync_at = None
    account.next_watch_attempt_at = None
    user.google_token = None
    db.flush()
    # Persist the connection and initial/update job together, even if Redis is
    # unavailable. Maintenance can dispatch the durable job after recovery.
    from app.features.mail_sync.service import READ_SCOPES
    from app.features.mail_sync.jobs import enqueue_sync
    if set(json.loads(account.scopes)) & READ_SCOPES:
        enqueue_sync(db, user.id, account.id)
    # enqueue_sync may reuse a job without committing. Reconnection flags and
    # refreshed credentials must still be persisted in that case.
    db.commit()
    return account


def credentials_for_user(db: Session, user) -> Credentials:
    account = find_account(db, user)
    if not account:
        raise HTTPException(409, "Reconnect Gmail before sending.")
    return credentials_for_account(db, user.id, account.id)


def credentials_for_account(db: Session, user_id: int, account_id: int) -> Credentials:
    # Serialize refresh and disconnect for an account across backend workers.
    account = db.query(ConnectedAccount).filter(
        ConnectedAccount.id == account_id, ConnectedAccount.user_id == user_id,
    ).populate_existing().with_for_update().first()
    if not account or not account.encrypted_credentials or account.requires_reauth:
        db.rollback()
        raise HTTPException(409, "Reconnect Gmail before sending.")
    try:
        credentials = Credentials.from_authorized_user_info(
            json.loads(decrypt(account.encrypted_credentials)))
        if not credentials.valid:
            credentials.refresh(partial(Request(), timeout=15))
            account.encrypted_credentials = encrypt(credentials.to_json())
        db.commit()
        return credentials
    except RefreshError as exc:
        if not exc.retryable:
            account.requires_reauth = True
            db.commit()
            raise HTTPException(409, "Gmail access expired. Please reconnect.") from None
        db.rollback()
        raise HTTPException(503, "Gmail is temporarily unavailable. Try again later.") from None
    except TransportError:
        db.rollback()
        raise HTTPException(503, "Gmail is temporarily unavailable. Try again later.") from None
    except (ValueError, TypeError, KeyError, InvalidToken):
        db.rollback()
        raise HTTPException(503, "Gmail credentials could not be loaded. Check server configuration.") from None


def disconnect_account(db: Session, user, account_id: int):
    account = db.query(ConnectedAccount).filter(
        ConnectedAccount.id == account_id, ConnectedAccount.user_id == user.id,
    ).with_for_update().first()
    if not account:
        raise HTTPException(404, "Connected account not found")
    if account.encrypted_credentials:
        data = json.loads(decrypt(account.encrypted_credentials))
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": data.get("refresh_token") or data["token"]}, timeout=15,
            )
        except requests.RequestException:
            db.rollback()
            raise HTTPException(502, "Google could not revoke access. Your connection is retained; try again.") from None
        # invalid_token means the grant was already revoked.
        try:
            already_revoked = response.status_code == 400 and response.json().get("error") == "invalid_token"
        except ValueError:
            already_revoked = False
        if response.status_code != 200 and not already_revoked:
            db.rollback()
            raise HTTPException(502, "Google could not revoke access. Your connection is retained; try again.")
    account.encrypted_credentials = None
    account.requires_reauth = False
    user.google_token = None
    db.commit()
