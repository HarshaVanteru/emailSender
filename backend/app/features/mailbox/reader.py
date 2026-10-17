from app.features.mailbox.models import MessageTriage
"""Read-only, owner-scoped cache queries. These methods never call Gmail."""
import base64
import binascii
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.orm import load_only

from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import EmailAttachment, EmailLabel, EmailMessage, MessageLabel
from app.features.mailbox.repository import mailbox_repository
from app.features.mail_sync.service import owned_account


def scope_key(*values):
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def encode_cursor(row, scope):
    return base64.urlsafe_b64encode(json.dumps([1, scope, row.internal_date, row.id]).encode()).decode().rstrip("=")


def decode_cursor(token, scope):
    try:
        data = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
        if (not isinstance(data, list) or len(data) != 4 or data[:2] != [1, scope]
                or type(data[2]) is not int or type(data[3]) is not int
                or not 0 <= data[2] < 2**63 or not 0 < data[3] < 2**31):
            raise ValueError()
        return data[2], data[3]
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(400, "Invalid page token for this account or filter.") from None


def has_label(label):
    return (EmailMessage.id.in_(
        # Account correlation is explicit even though internal message IDs are unique.
        select(MessageLabel.message_id).join(
            EmailLabel, and_(EmailLabel.id == MessageLabel.label_id, EmailLabel.account_id == MessageLabel.account_id)
        ).where(MessageLabel.account_id == EmailMessage.account_id, EmailLabel.gmail_label_id == label)
    ))


def serialize_messages(db, account_id, rows, detail=False):
    ids = [row.id for row in rows]
    if not ids:
        return []
    labels = {key: [] for key in ids}
    for message_id, gmail_id in db.query(MessageLabel.message_id, EmailLabel.gmail_label_id).join(
        EmailLabel, and_(EmailLabel.id == MessageLabel.label_id, EmailLabel.account_id == MessageLabel.account_id)
    ).filter(MessageLabel.account_id == account_id, MessageLabel.message_id.in_(ids)).order_by(EmailLabel.gmail_label_id):
        labels[message_id].append(gmail_id)
    attachments = {key: [] for key in ids}
    for item in db.query(EmailAttachment).filter(EmailAttachment.account_id == account_id,
                                                EmailAttachment.message_id.in_(ids)).order_by(EmailAttachment.id):
        attachments[item.message_id].append({"id": item.id, "filename": item.filename,
                                              "mime_type": item.mime_type, "size_bytes": item.size_bytes})
    triage = {item.message_id: item for item in db.query(MessageTriage).filter(
        MessageTriage.account_id == account_id, MessageTriage.message_id.in_(ids), MessageTriage.state == "succeeded")}
    result = []
    for row in rows:
        value = {"id": row.id, "account_id": row.account_id, "thread_id": row.thread_id,
                 "from_address": row.from_address or "", "subject": row.subject or "",
                 "snippet": row.snippet or "", "internal_date": row.internal_date,
                 "labels": labels[row.id], "has_attachments": bool(attachments[row.id])}
        classified = triage.get(row.id)
        value.update(ai_importance=classified.importance if classified else None,
                     ai_is_spam=bool(classified.is_spam) if classified else None,
                     ai_category=classified.category if classified else None,
                     ai_reason=classified.reason if classified else None)
        if detail:
            value.update(to_addresses=row.to_addresses, cc_addresses=row.cc_addresses,
                         body_text=row.body_text, body_html=row.body_html, attachments=attachments[row.id])
        result.append(value)
    return result


def list_messages(db, user_id, account_id, *, label=None, unread=None, q="", page_size=30, page_token=None, thread_id=None, importance=None):
    owned_account(db, user_id, account_id)
    q = q.strip()
    scope = scope_key(user_id, account_id, label, unread, q, thread_id)
    if importance is not None:
        if label != "MYBOX" or importance not in {"critical", "high", "normal", "low"}:
            raise HTTPException(400, "Importance filtering requires Mybox and a valid importance level.")
        scope = scope_key(scope, importance)
    query = db.query(EmailMessage).join(ConnectedAccount, ConnectedAccount.id == EmailMessage.account_id).filter(
        ConnectedAccount.user_id == user_id, EmailMessage.account_id == account_id)
    if thread_id is not None:
        query = query.filter(EmailMessage.thread_id == thread_id)
    else:
        # List responses never load bodies or RFC headers into Python.
        query = query.options(load_only(EmailMessage.id, EmailMessage.account_id, EmailMessage.thread_id,
                              EmailMessage.from_address, EmailMessage.subject, EmailMessage.snippet, EmailMessage.internal_date))
    if label == "MYBOX":
        query = query.join(MessageTriage, and_(MessageTriage.account_id == EmailMessage.account_id,
            MessageTriage.message_id == EmailMessage.id)).filter(
            MessageTriage.state == "succeeded", MessageTriage.is_spam == 0,
            ~has_label("SPAM"), ~has_label("TRASH"), ~has_label("SENT"), ~has_label("DRAFT"))
        if importance is not None:
            query = query.filter(MessageTriage.importance == importance)
    elif label:
        query = query.filter(has_label(label))
    if unread is not None:
        query = query.filter(has_label("UNREAD") if unread else ~has_label("UNREAD"))
    if q:
        # Literal substring search, not Gmail query syntax. Wildcards are escaped.
        term = q.lower().replace("/", "//").replace("%", "/%").replace("_", "/_")
        query = query.filter(or_(*[func.lower(field).like(f"%{term}%", escape="/") for field in (
            EmailMessage.subject, EmailMessage.from_address, EmailMessage.snippet, EmailMessage.body_text,
            cast(EmailMessage.to_addresses, Text), cast(EmailMessage.cc_addresses, Text))]))
    if page_token:
        date, row_id = decode_cursor(page_token, scope)
        compare_date = EmailMessage.internal_date > date if thread_id is not None else EmailMessage.internal_date < date
        compare_id = EmailMessage.id > row_id if thread_id is not None else EmailMessage.id < row_id
        query = query.filter(or_(compare_date, and_(EmailMessage.internal_date == date, compare_id)))
    order = (EmailMessage.internal_date.asc(), EmailMessage.id.asc()) if thread_id is not None else (
        EmailMessage.internal_date.desc(), EmailMessage.id.desc())
    rows = query.order_by(*order).limit(page_size + 1).all()
    more = len(rows) > page_size
    rows = rows[:page_size]
    return {"items": serialize_messages(db, account_id, rows, detail=thread_id is not None),
            "next_page_token": encode_cursor(rows[-1], scope) if more else None}


def read_message(db, user_id, account_id, message_id):
    row = mailbox_repository.get_message(db, user_id, account_id, message_id)
    if row is None:
        raise HTTPException(404, "Message not found")
    return serialize_messages(db, account_id, [row], detail=True)[0]


def read_thread(db, user_id, account_id, thread_id, page_size=10, page_token=None):
    thread = mailbox_repository.get_thread(db, user_id, account_id, thread_id)
    if thread is None:
        raise HTTPException(404, "Conversation not found")
    return {"id": thread.id, "subject": thread.subject or "", "account_id": account_id,
            **list_messages(db, user_id, account_id, thread_id=thread_id, page_size=page_size, page_token=page_token)}


def list_labels(db, user_id, account_id):
    owned_account(db, user_id, account_id)
    return [{"id": item.gmail_label_id, "name": item.name, "type": item.type} for item in
            db.query(EmailLabel).filter_by(account_id=account_id).order_by(EmailLabel.type, EmailLabel.name, EmailLabel.id)]
