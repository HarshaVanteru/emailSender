"""Verified Gmail push hints and renewable users.watch registrations."""
import base64
import binascii
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from sqlalchemy import or_

from app.core import config
from app.core.database import SessionLocal
from app.features.google_login.models import ConnectedAccount
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.features.mail_sync.service import SyncFailure, check_read_access, history_cursor, owned_account, utcnow
from app.features.mail_sync.jobs import dispatch_job, enqueue_sync
from app.workers.rate_limit import GmailRateLimiter

_RESOURCE = re.compile(r"^projects/[A-Za-z0-9._~+%-]+/(topics|subscriptions)/[A-Za-z0-9._~+%-]+$")


def push_configured():
    return bool(config.GMAIL_PUSH_TOPIC and config.PUBSUB_PUSH_AUDIENCE
                and config.PUBSUB_PUSH_SERVICE_ACCOUNT and config.PUBSUB_SUBSCRIPTION
                and _RESOURCE.fullmatch(config.GMAIL_PUSH_TOPIC)
                and _RESOURCE.fullmatch(config.PUBSUB_SUBSCRIPTION)
                and "/topics/" in config.GMAIL_PUSH_TOPIC
                and "/subscriptions/" in config.PUBSUB_SUBSCRIPTION)


def verify_push_token(authorization):
    if not push_configured():
        raise HTTPException(503, "Gmail push is not configured.")
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 8192:
        raise HTTPException(401, "Invalid push authentication.")
    try:
        claims = id_token.verify_oauth2_token(
            authorization[7:], Request(), audience=config.PUBSUB_PUSH_AUDIENCE)
    except Exception:
        raise HTTPException(401, "Invalid push authentication.") from None
    if (claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or claims.get("email") != config.PUBSUB_PUSH_SERVICE_ACCOUNT
            or claims.get("email_verified") is not True):
        raise HTTPException(401, "Invalid push authentication.")


def parse_push(body):
    try:
        envelope = json.loads(body)
        if (not isinstance(envelope, dict) or envelope.get("subscription") != config.PUBSUB_SUBSCRIPTION
                or not isinstance(envelope.get("message"), dict)):
            raise ValueError()
        message = envelope["message"]
        if not isinstance(message.get("messageId"), str) or not message["messageId"]:
            raise ValueError()
        encoded = message["data"]
        if not isinstance(encoded, str) or len(encoded) > 8192:
            raise ValueError()
        notice = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(notice, dict):
            raise ValueError()
        email = notice["emailAddress"]
        cursor = history_cursor(notice["historyId"])
        if (not isinstance(email, str) or len(email) > 255 or "@" not in email
                or not cursor.isdecimal()):
            raise ValueError()
        return email.lower(), cursor
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, SyncFailure):
        raise HTTPException(400, "Invalid Pub/Sub push envelope.") from None


def accept_notification(db, email, cursor):
    account = db.query(ConnectedAccount).filter_by(gmail_email=email).first()
    if account is None or account.sync_paused:
        return
    try:
        check_read_access(account)
    except HTTPException:
        return
    if account.history_id and int(cursor) <= int(account.history_id):
        return
    # A notification is only a hint. The worker reads Gmail and owns history_id.
    job = enqueue_sync(db, account.user_id, account.id)
    dispatch_job(db, job.id)


def renew_watch(db, user_id, account_id, *, service=None, limiter=None):
    if not push_configured():
        return False
    account = owned_account(db, user_id, account_id)
    try:
        check_read_access(account)
        if service is None:
            credentials = credentials_for_account(db, user_id, account_id)
            service = gmail_service.get_gmail_service(credentials.to_json())
        gate = limiter if limiter is not None else GmailRateLimiter()
        gate.wait(account_id)
        result = service.users().watch(userId="me", body={"topicName": config.GMAIL_PUSH_TOPIC}).execute(num_retries=0)
        expires_ms = int(result["expiration"])
        history_cursor(result["historyId"])
        expires = datetime.fromtimestamp(expires_ms / 1000, timezone.utc).replace(tzinfo=None)
        if expires <= utcnow() + timedelta(hours=1):
            raise ValueError("Invalid watch expiration")
        account = owned_account(db, user_id, account_id, lock=True)
        account.watch_expiration = expires
        account.next_watch_attempt_at = max(utcnow() + timedelta(hours=1),
                                            min(utcnow() + timedelta(days=1), expires - timedelta(days=1)))
        db.commit()
        return True
    except Exception:
        db.rollback()
        try:
            account = owned_account(db, user_id, account_id, lock=True)
            account.next_watch_attempt_at = utcnow() + timedelta(hours=1)
            db.commit()
        except Exception:
            db.rollback()
        return False


def renew_due_watches(session_factory=SessionLocal, service_factory=None, limiter=None):
    if not push_configured():
        return 0
    with session_factory() as db:
        now = utcnow()
        rows = db.query(ConnectedAccount.id, ConnectedAccount.user_id).filter(
            ConnectedAccount.encrypted_credentials.is_not(None),
            ConnectedAccount.requires_reauth.is_(False),
            or_(ConnectedAccount.next_watch_attempt_at.is_(None), ConnectedAccount.next_watch_attempt_at <= now),
            or_(ConnectedAccount.watch_expiration.is_(None),
                ConnectedAccount.watch_expiration <= now + timedelta(days=1)),
        ).order_by(ConnectedAccount.next_watch_attempt_at, ConnectedAccount.id).limit(20).all()
        db.rollback()
        count = 0
        for account_id, user_id in rows:
            if renew_watch(db, user_id, account_id,
                           service=service_factory() if service_factory else None, limiter=limiter):
                count += 1
        return count
