"""Transactional sync engine invoked by durable workers.

One account row lock serializes sync writers. A single transaction commits cache
changes and its cursor. Provider failures roll back both, then mark the job failed.
"""
import json
from datetime import timedelta, timezone
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from sqlalchemy.exc import OperationalError

from app.core.time import utcnow
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import AuditLog, EmailAttachment, EmailLabel, EmailMessage, EmailThread, MessageLabel, SyncJob
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.mime import InvalidMessage, normalize_message, provider_id
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.adapter import GmailAdapter

READ_SCOPES = {"https://mail.google.com/", "https://www.googleapis.com/auth/gmail.readonly",
               "https://www.googleapis.com/auth/gmail.modify"}
PAGE_SIZE = 100
MAX_HISTORY_PAGES = 100
MAX_CHANGED_MESSAGES = 2000
SYSTEM_LABELS = {"INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "UNREAD", "STARRED", "IMPORTANT",
                 "CHAT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
_before_request = ContextVar("gmail_sync_before_request", default=None)


@contextmanager
def request_guard(callback):
    token = _before_request.set(callback)
    try:
        yield
    finally:
        _before_request.reset(token)


class SyncFailure(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status


class HistoryExpired(Exception):
    pass


def owned_account(db, user_id, account_id, lock=False):
    query = db.query(ConnectedAccount).filter(ConnectedAccount.id == account_id, ConnectedAccount.user_id == user_id)
    if lock:
        query = query.populate_existing().with_for_update(nowait=True)
    account = query.first()
    if not account:
        raise HTTPException(404, "Connected account not found")
    return account


def check_read_access(account):
    if not account.encrypted_credentials or account.requires_reauth:
        raise HTTPException(409, "Reconnect Gmail before synchronizing.")
    try:
        scopes = set(json.loads(account.scopes))
    except (ValueError, TypeError):
        raise HTTPException(503, "Stored Gmail permission information is invalid.") from None
    if not scopes & READ_SCOPES:
        raise HTTPException(409, "Mailbox read permission is required. Connect via /api/v1/auth/google?mailbox_access=true.")


def execute(request):
    guard = _before_request.get()
    if guard is not None:
        guard()
    return request.execute(num_retries=0)


def history_cursor(value):
    if not isinstance(value, str) or not value.isdecimal() or len(value) > 255:
        raise SyncFailure("invalid_history_cursor")
    return value


def changed_messages(service, cursor):
    changed, page_tokens = set(), set()
    token = None
    for _ in range(MAX_HISTORY_PAGES):
        options = {"startHistoryId": cursor, "maxResults": 600}
        if token:
            options["pageToken"] = token
        try:
            page = execute(GmailAdapter(service).history(**options))
        except HttpError as exc:
            if exc.resp.status == 404:
                raise HistoryExpired() from None
            raise
        for event in page.get("history", []):
            for kind in ("messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
                for change in event.get(kind, []):
                    changed.add(provider_id(change["message"]["id"]))
            # Older/unusual history responses may have only generic message IDs.
            for message in event.get("messages", []):
                changed.add(provider_id(message["id"]))
        if len(changed) > MAX_CHANGED_MESSAGES:
            raise SyncFailure("sync_message_budget_exceeded", 409)
        token = page.get("nextPageToken")
        if not token:
            return changed, history_cursor(page.get("historyId"))
        if token in page_tokens:
            raise SyncFailure("repeated_history_page")
        page_tokens.add(token)
    raise SyncFailure("sync_history_budget_exceeded", 409)


def reconciliation_messages(db, service, account):
    """Read one page inside a fixed recent window. Older history is explicit."""
    if account.repair_after_id is not None:
        changed = repair_cached_page(db, account)
        return changed, history_cursor(account.mail_import_history_id)
    if account.mail_import_started_at is None:
        profile = execute(GmailAdapter(service).profile())
        if profile.get("emailAddress", "").lower() != account.gmail_email.lower():
            raise SyncFailure("mailbox_identity_mismatch", 409)
        # Replay changes from BEFORE the first page only after the scan finishes.
        account.mail_import_history_id = history_cursor(profile.get("historyId"))
        account.mail_import_started_at = utcnow()
        account.mail_import_page_token = None
        account.mail_import_seen_tokens = []
        account.mail_import_complete = False
    cutoff = int((account.mail_import_started_at - timedelta(days=account.initial_sync_days)).replace(tzinfo=timezone.utc).timestamp())
    options = {"maxResults": PAGE_SIZE, "includeSpamTrash": True, "q": f"after:{cutoff}"}
    token = account.mail_import_page_token
    if token:
        options["pageToken"] = token
    try:
        page = execute(GmailAdapter(service).list_messages(**options))
    except HttpError as exc:
        if token and exc.resp.status in (400, 404):
            # Gmail page tokens can expire. Restart the listing safely; cached
            # pages remain readable and the committed history cursor is retained.
            account.mail_import_started_at = None
            return reconciliation_messages(db, service, account)
        raise
    changed = {provider_id(message["id"]) for message in page.get("messages", [])}
    next_token = page.get("nextPageToken")
    seen = account.mail_import_seen_tokens or []
    if next_token:
        if not isinstance(next_token, str) or next_token in seen:
            raise SyncFailure("repeated_message_page")
        account.mail_import_seen_tokens = [*seen, next_token]
    account.mail_import_page_token = next_token
    account.mail_import_complete = not next_token
    if not next_token and account.history_id:
        # Repair previously imported mail explicitly; absence from a limited
        # recent listing never proves a provider deletion.
        account.repair_after_id = 0
        changed.update(repair_cached_page(db, account))
    return changed, history_cursor(account.mail_import_history_id)


def repair_cached_page(db, account):
    rows = db.query(EmailMessage.id, EmailMessage.gmail_message_id).filter(
        EmailMessage.account_id == account.id, EmailMessage.id > account.repair_after_id
    ).order_by(EmailMessage.id).limit(PAGE_SIZE + 1).all()
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    account.repair_after_id = rows[-1][0] if more else None
    account.mail_import_complete = not more
    return {row[1] for row in rows}


def refresh_labels(db, service, account_id):
    items = execute(GmailAdapter(service).labels())["labels"]
    existing = {label.gmail_label_id: label for label in db.query(EmailLabel).filter_by(account_id=account_id).all()}
    seen = set()
    for item in items:
        gmail_id = provider_id(item["id"])
        seen.add(gmail_id)
        label = existing.get(gmail_id)
        if label is None:
            label = EmailLabel(account_id=account_id, gmail_label_id=gmail_id)
            db.add(label)
        label.name = item["name"]
        label.type = item["type"]
        existing[gmail_id] = label
    for gmail_id in set(existing) - seen:
        label = existing.pop(gmail_id)
        db.query(MessageLabel).filter_by(account_id=account_id, label_id=label.id).delete(synchronize_session=False)
        db.delete(label)
    db.flush()
    return existing


def remove_message(db, account_id, gmail_id, affected_threads):
    message = db.query(EmailMessage).filter_by(account_id=account_id, gmail_message_id=gmail_id).first()
    if message is not None:
        affected_threads.add(message.thread_id)
        # Explicit child deletes work even if a test/dev SQLite FK switch is off.
        db.query(MessageLabel).filter_by(account_id=account_id, message_id=message.id).delete(synchronize_session=False)
        db.query(EmailAttachment).filter_by(account_id=account_id, message_id=message.id).delete(synchronize_session=False)
        db.delete(message)
        db.flush()


def upsert_message(db, account_id, data, labels, affected_threads):
    message = db.query(EmailMessage).filter_by(account_id=account_id, gmail_message_id=data["gmail_message_id"]).first()
    inserted = message is None
    if (message is not None and message.gmail_history_id and data.get("gmail_history_id")
            and int(data["gmail_history_id"]) < int(message.gmail_history_id)):
        return  # Reject stale snapshots before creating any new thread/label rows.
    thread = db.query(EmailThread).filter_by(account_id=account_id, gmail_thread_id=data["gmail_thread_id"]).first()
    if thread is None:
        thread = EmailThread(account_id=account_id, gmail_thread_id=data["gmail_thread_id"])
        db.add(thread)
        db.flush()
    if message is None:
        message = EmailMessage(account_id=account_id, thread_id=thread.id)
        db.add(message)
    else:
        affected_threads.add(message.thread_id)
    affected_threads.add(thread.id)
    message.thread_id = thread.id
    for field in ("gmail_message_id", "gmail_history_id", "internal_date", "size_estimate", "from_address",
                  "to_addresses", "cc_addresses", "bcc_addresses", "subject", "snippet", "headers", "body_text", "body_html"):
        setattr(message, field, data[field])
    message.cached_at = utcnow()
    db.flush()

    db.query(MessageLabel).filter_by(account_id=account_id, message_id=message.id).delete(synchronize_session=False)
    for gmail_id in data["labels"]:
        if gmail_id not in labels:
            # A label can be created after the catalog request. Preserve the ID;
            # its actual name/type will be refreshed by the next label catalog.
            label = EmailLabel(account_id=account_id, gmail_label_id=gmail_id, name=gmail_id,
                               type="system" if gmail_id in SYSTEM_LABELS else "user")
            db.add(label)
            db.flush()
            labels[gmail_id] = label
        db.add(MessageLabel(account_id=account_id, message_id=message.id, label_id=labels[gmail_id].id))
    existing = {part.mime_part_id: part for part in db.query(EmailAttachment).filter_by(account_id=account_id, message_id=message.id).all()}
    seen = set()
    for part in data["attachments"]:
        part_id = part["mime_part_id"]
        if part_id in seen:
            raise InvalidMessage("duplicate_mime_part_id")
        seen.add(part_id)
        attachment = existing.get(part_id)
        if attachment is None:
            attachment = EmailAttachment(account_id=account_id, message_id=message.id)
            db.add(attachment)
        for field, value in part.items():
            setattr(attachment, field, value)
    for part_id in set(existing) - seen:
        db.delete(existing[part_id])
    db.flush()
    return 'inserted' if inserted else 'updated'


def refresh_threads(db, account_id, affected):
    for thread_id in affected:
        thread = db.query(EmailThread).filter_by(account_id=account_id, id=thread_id).one()
        newest = db.query(EmailMessage).filter_by(account_id=account_id, thread_id=thread_id).order_by(
            EmailMessage.internal_date.desc(), EmailMessage.id.desc()).first()
        if newest is None:
            db.delete(thread)
        else:
            thread.subject, thread.snippet, thread.last_message_at = newest.subject, newest.snippet, newest.internal_date
    db.flush()


def apply_sync(db, account, service, reconcile=False, progress=None):
    """Apply a complete sync without committing; caller owns locks/transaction."""
    account_id = account.id
    if account.history_id and account.mail_import_complete and not reconcile:
        try:
            changed, cursor = changed_messages(service, account.history_id)
            kind = "incremental"
        except HistoryExpired:
            kind = "reconcile"
            changed, cursor = reconciliation_messages(db, service, account)
        except SyncFailure as exc:
            if exc.code not in {"sync_message_budget_exceeded", "sync_history_budget_exceeded"}:
                raise
            # A large backlog must not permanently block all-mail delivery.
            # Rebuild it through bounded, resumable pages instead.
            kind = "reconcile"
            changed, cursor = reconciliation_messages(db, service, account)
    else:
        kind = "reconcile" if reconcile else "initial"
        changed, cursor = reconciliation_messages(db, service, account)
        if account.history_id and not account.mail_import_complete:
            # New mail keeps moving while a recent-window scan is paginated.
            try:
                updates, current = changed_messages(service, account.history_id)
                changed.update(updates)
                cursor = max((cursor, current), key=int)
            except HistoryExpired:
                # Expiration during a paginated repair needs a fresh repair
                # baseline, never a silent cursor reset or regression.
                account.mail_import_started_at = None
                account.repair_after_id = None
                extra, cursor = reconciliation_messages(db, service, account)
                changed.update(extra)
    if account.history_id and int(cursor) < int(account.history_id):
        raise SyncFailure("history_cursor_regressed")
    labels = refresh_labels(db, service, account_id)
    affected_threads = set()
    if progress is None:
        progress = {'seen': 0, 'inserted': 0, 'updated': 0}
    for gmail_id in sorted(changed):
        progress['seen'] += 1
        try:
            raw = execute(GmailAdapter(service).message(gmail_id))
        except HttpError as exc:
            if exc.resp.status == 404:
                remove_message(db, account_id, gmail_id, affected_threads)
                continue
            raise
        if raw.get("id") != gmail_id:
            raise InvalidMessage("message_identity_mismatch")
        def load_body(attachment_id):
            return execute(GmailAdapter(service).attachment(gmail_id, attachment_id))["data"]
        outcome = upsert_message(db, account_id, normalize_message(raw, load_body), labels, affected_threads)
        if outcome:
            progress[outcome] += 1
    if account.mail_import_complete and account.mail_import_started_at is not None:
        # A recent listing is not an authoritative full-mailbox deletion set.
        account.mail_import_started_at = None
        account.mail_import_history_id = None
        account.mail_import_seen_tokens = None
    refresh_threads(db, account_id, affected_threads)
    account.history_id = cursor
    account.last_synced_at = utcnow()
    return kind


def job_payload(job):
    return {"id": job.id, "account_id": job.account_id, "kind": job.kind, "status": job.status,
            "attempts": job.attempts, "created_at": job.created_at, "started_at": job.started_at,
            "finished_at": job.finished_at, "error_code": job.error_code,
            "available_at": job.available_at, "messages_seen": job.messages_seen,
            "messages_inserted": job.messages_inserted, "messages_updated": job.messages_updated}


def synchronize(db, user_id: int, account_id: int, reconcile=False, service=None):
    """In-process harness for isolated engine verification; API uses the outbox."""
    account = owned_account(db, user_id, account_id)
    check_read_access(account)
    kind = "reconcile" if reconcile else "incremental" if account.history_id else "initial"
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
    job = SyncJob(account_id=account_id, kind=kind, status="running", attempts=1, started_at=utcnow())
    db.add(job)
    db.commit()
    job_id = job.id
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_read_access(account)
        if service is None:
            service = gmail_service.get_gmail_service(credentials.to_json())
        progress = {'seen': 0, 'inserted': 0, 'updated': 0}
        kind = apply_sync(db, account, service, reconcile, progress)
        job.messages_seen, job.messages_inserted, job.messages_updated = progress['seen'], progress['inserted'], progress['updated']
        job.kind, job.status, job.finished_at = kind, "succeeded", utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="mailbox.sync", resource_type="sync_job",
                        resource_id=str(job_id), outcome="success"))
        db.commit()
        return job_payload(job)
    except Exception as exc:
        db.rollback()
        if isinstance(exc, SyncFailure):
            code, status = exc.code, exc.status
        elif isinstance(exc, HTTPException):
            code, status = "connection_unavailable", exc.status_code
        elif isinstance(exc, HttpError):
            code, status = f"gmail_http_{exc.resp.status}", 502
        elif isinstance(exc, (InvalidMessage, ValueError, KeyError, TypeError)):
            code, status = "invalid_gmail_payload", 502
        elif isinstance(exc, OperationalError):
            mysql_code = getattr(exc.orig, "args", [None])[0]
            if mysql_code in (1205, 3572):
                code, status = "sync_busy", 409
            else:
                code, status = "sync_database_unavailable", 503
        else:
            code, status = "sync_failed", 502
        job = db.get(SyncJob, job_id)
        job.kind, job.status, job.finished_at, job.error_code = kind, "failed", utcnow(), code
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="mailbox.sync", resource_type="sync_job",
                        resource_id=str(job_id), outcome="failure"))
        db.commit()
        raise HTTPException(status, {"message": "Synchronization failed; the committed cursor was retained.",
                                     "job_id": job_id, "error_code": code}) from None
