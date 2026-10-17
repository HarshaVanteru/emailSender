"""Explicit user-initiated Gmail mutations with authoritative cache reconciliation."""
import json

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError

from app.core.config import GMAIL_MODIFY_SCOPE
from app.features.mailbox.models import AuditLog, EmailLabel, EmailMessage, MessageLabel
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.features.mail_sync.service import SYSTEM_LABELS, owned_account, utcnow
from app.features.mailbox.reader import serialize_messages
from app.workers.rate_limit import GmailRateLimiter

MODIFY_SCOPES = {GMAIL_MODIFY_SCOPE, "https://mail.google.com/"}


def check_modify_access(account):
    if not account.encrypted_credentials or account.requires_reauth:
        raise HTTPException(409, "Reconnect Gmail before changing mail.")
    try:
        scopes = set(json.loads(account.scopes))
    except (ValueError, TypeError):
        raise HTTPException(503, "Stored Gmail permission information is invalid.") from None
    if not scopes & MODIFY_SCOPES:
        raise HTTPException(409, "Gmail change permission is required. Reconnect with modify_access=true.")


def apply_labels(db, account_id, message, provider):
    """Replace one message's labels from Google's response; caller holds account lock."""
    ids = provider.get("labelIds")
    if provider.get("id") != message.gmail_message_id or not isinstance(ids, list) or any(
            not isinstance(label, str) or not label or len(label) > 128 for label in ids):
        raise HTTPException(502, "Gmail changed the message, but its new state could not be verified. Sync mail to refresh it.")
    labels = set(ids)
    db.query(MessageLabel).filter_by(account_id=account_id, message_id=message.id).delete(synchronize_session=False)
    for gmail_id in sorted(labels):
        row = db.query(EmailLabel).filter_by(account_id=account_id, gmail_label_id=gmail_id).first()
        if row is None:
            row = EmailLabel(account_id=account_id, gmail_label_id=gmail_id, name=gmail_id,
                             type="system" if gmail_id in SYSTEM_LABELS else "user")
            db.add(row)
            db.flush()
        db.add(MessageLabel(account_id=account_id, message_id=message.id, label_id=row.id))
    db.flush()


def change_message(db, user_id, account_id, message_id, *, read=None, starred=None, action=None,
                   service=None, limiter=None):
    if action not in (None, "archive", "trash") or (action and (read is not None or starred is not None)) or (
            action is None and read is None and starred is None):
        raise HTTPException(422, "Choose a supported mail action.")
    account = owned_account(db, user_id, account_id)
    check_modify_access(account)
    message = db.query(EmailMessage).filter_by(account_id=account_id, id=message_id).first()
    if message is None:
        raise HTTPException(404, "Message not found")
    # Refreshing credentials commits; validate before and after this boundary.
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
        service = gmail_service.get_gmail_service(credentials.to_json())
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_modify_access(account)
        message = db.query(EmailMessage).filter_by(account_id=account_id, id=message_id).populate_existing().first()
        if message is None:
            raise HTTPException(404, "Message not found")
        gate = limiter if limiter is not None else GmailRateLimiter()
        gate.wait(account_id)
        if action == "trash":
            response = service.users().messages().trash(userId="me", id=message.gmail_message_id).execute(num_retries=0)
        else:
            add, remove = [], []
            if read is not None:
                (remove if read else add).append("UNREAD")
            if starred is not None:
                (add if starred else remove).append("STARRED")
            if action == "archive":
                remove.append("INBOX")
            response = service.users().messages().modify(
                userId="me", id=message.gmail_message_id,
                body={"addLabelIds": add, "removeLabelIds": remove}).execute(num_retries=0)
        apply_labels(db, account_id, message, response)
        if response.get("historyId") is not None:
            message.gmail_history_id = str(response["historyId"])
        account.next_sync_at = utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="mailbox." + (action or "modify"),
                        resource_type="message", resource_id=str(message_id), outcome="success"))
        db.commit()
        return serialize_messages(db, account_id, [message], detail=True)[0]
    except HttpError as exc:
        db.rollback()
        status = exc.resp.status
        if status == 404:
            raise HTTPException(409, "Gmail could not find this cached message. Sync mail to refresh it.") from None
        if status in (401, 403):
            raise HTTPException(409, "Gmail rejected this change. Check the connection and change permission.") from None
        raise HTTPException(503, "Gmail could not complete this change. Refresh the mailbox before trying again.") from None
    except RedisError:
        db.rollback()
        raise HTTPException(503, "The mail service is temporarily unavailable. Try again later.") from None
    except OperationalError:
        db.rollback()
        raise HTTPException(503, "The mailbox is busy or unavailable. Refresh and try again.") from None
