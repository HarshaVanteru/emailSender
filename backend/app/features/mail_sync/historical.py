"""One explicitly requested historical page per durable session transition."""
import hashlib
import secrets
from datetime import timedelta, timezone

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.time import utcnow
from app.core.token_crypto import encrypt, decrypt
from app.features.google_login.accounts import credentials_for_account
from app.features.mail_sync.history_models import HistorySession
from app.features.mail_sync.service import (
    owned_account, check_read_access, execute, refresh_labels, upsert_message,
    refresh_threads, request_guard, SyncFailure,
)
from app.features.mail_sync.events import publish_update
from app.integrations.gmail.adapter import GmailAdapter
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.mime import normalize_message, provider_id
from app.workers.rate_limit import GmailRateLimiter


def payload(row):
    return {"session_id": row.id, "status": row.status, "messages_imported": row.messages_imported,
            "has_more": row.status != "completed", "error_code": row.error_code}


def get_session(db, user_id, account_id, session_id):
    owned_account(db, user_id, account_id)
    row = db.query(HistorySession).filter_by(id=session_id, account_id=account_id, user_id=user_id).first()
    if not row:
        raise HTTPException(404, "Historical session not found.")
    return row


def request_page(db, user_id, account_id, *, session_id=None, label=None):
    account = owned_account(db, user_id, account_id, lock=True)
    check_read_access(account)
    if session_id:
        row = get_session(db, user_id, account_id, session_id)
        if row.expires_at <= utcnow():
            raise HTTPException(410, "Historical session expired. Start a new request.")
    else:
        # Each account/view has one resumable session. Its boundary stays fixed.
        scope = hashlib.sha256((label or "").encode()).hexdigest()
        row = db.query(HistorySession).filter_by(account_id=account_id, scope_key=scope).first()
        if row and row.expires_at <= utcnow():
            db.delete(row)
            db.flush()
            row = None
        if not row:
            boundary = account.mail_import_started_at or account.last_synced_at or utcnow()
            before = int((boundary - timedelta(days=account.initial_sync_days)).replace(tzinfo=timezone.utc).timestamp())
            row = HistorySession(id=secrets.token_hex(32), user_id=user_id, account_id=account_id,
                scope_key=scope, label=label, before_epoch=before, status="pending", attempts=0,
                messages_imported=0, seen_tokens=[], available_at=utcnow(), expires_at=utcnow() + timedelta(days=7))
            db.add(row)
    if row.status == "failed" or (row.status == "ready" and session_id):
        row.status, row.attempts, row.available_at, row.error_code = "pending", 0, utcnow(), None
    db.commit()
    return payload(row)


def process_page(session_id, session_factory=SessionLocal, service=None, limiter=None):
    with session_factory() as db:
        row = db.query(HistorySession).filter_by(id=session_id).first()
        if not row or row.status != "pending" or row.available_at > utcnow():
            return
        user_id, account_id = row.user_id, row.account_id
        try:
            if service is None:
                credentials = credentials_for_account(db, user_id, account_id)
                service = gmail_service.get_gmail_service(credentials.to_json())
            account = owned_account(db, user_id, account_id, lock=True)
            check_read_access(account)
            row = db.query(HistorySession).filter_by(id=session_id).populate_existing().with_for_update().one()
            if row.status != "pending" or row.available_at > utcnow():
                db.rollback()
                return
            if row.expires_at <= utcnow():
                row.status = "expired"
                db.commit()
                return
            adapter = GmailAdapter(service)
            options = {"maxResults": 100, "includeSpamTrash": True, "q": f"before:{row.before_epoch + 1}"}
            if row.label:
                options["labelIds"] = [row.label]
            if row.page_token_ciphertext:
                options["pageToken"] = decrypt(row.page_token_ciphertext)
            gate = limiter or GmailRateLimiter()
            with request_guard(lambda: gate.wait(account_id)):
                try:
                    page = execute(adapter.list_messages(**options))
                except HttpError as exc:
                    if exc.resp.status not in (400, 404) or not row.page_token_ciphertext:
                        raise
                    # Re-list from the stable boundary; deduplication makes restart safe.
                    options.pop("pageToken")
                    row.seen_tokens = []
                    page = execute(adapter.list_messages(**options))
                labels = refresh_labels(db, service, account_id)
                affected = set()
                for item in page.get("messages", []):
                    gmail_id = provider_id(item["id"])
                    try:
                        raw = execute(adapter.message(gmail_id))
                    except HttpError as exc:
                        if exc.resp.status == 404:
                            continue
                        raise
                    if raw.get("id") != gmail_id:
                        raise SyncFailure("message_identity_mismatch")
                    data = normalize_message(raw, lambda aid: execute(adapter.attachment(gmail_id, aid))["data"])
                    upsert_message(db, account_id, data, labels, affected)
                refresh_threads(db, account_id, affected)
            next_token = page.get("nextPageToken")
            if next_token:
                token_hash = hashlib.sha256(next_token.encode()).hexdigest()
                if token_hash in row.seen_tokens:
                    raise SyncFailure("repeated_message_page")
                row.seen_tokens = [*row.seen_tokens, token_hash]
            row.page_token_ciphertext = encrypt(next_token) if next_token else None
            row.status = "ready" if next_token else "completed"
            row.messages_imported += len(page.get("messages", []))
            row.attempts, row.error_code = 0, None
            from app.features.google_login.accounts import persist_provider_refresh
            persist_provider_refresh(account, service)
            db.commit()  # The page and continuation checkpoint are atomic.
            publish_update(account_id)
        except Exception as exc:
            db.rollback()
            from app.features.mail_sync.jobs import classify_failure
            code, retryable = classify_failure(exc)
            row = db.query(HistorySession).filter_by(id=session_id).with_for_update().first()
            if row and row.status == "pending":
                row.attempts += 1
                row.error_code = code
                row.status = "pending" if retryable and row.attempts < 4 else "failed"
                row.available_at = utcnow() + timedelta(seconds=min(300, 15 * 2 ** row.attempts))
                db.commit()


def dispatch_pending(db, publisher):
    ids = [row[0] for row in db.query(HistorySession.id).filter(
        HistorySession.status == "pending", HistorySession.available_at <= utcnow()).limit(100)]
    db.rollback()
    for session_id in ids:
        publisher("mailbox.historical", args=[session_id], queue="gmail-sync", retry=False)
