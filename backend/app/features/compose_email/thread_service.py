"""Prepare and send user-reviewed replies or forwards from cached messages."""
import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import getaddresses

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError

from app.core.config import GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE
from app.features.mailbox.models import AuditLog, EmailAttachment, EmailMessage, EmailThread
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.text import html_to_text
from app.integrations.gmail.client import gmail_service
from app.features.mail_sync.service import owned_account, utcnow
from app.workers.rate_limit import GmailRateLimiter

SEND_SCOPES = {'https://www.googleapis.com/auth/gmail.send', GMAIL_COMPOSE_SCOPE,
               GMAIL_MODIFY_SCOPE, 'https://mail.google.com/'}
MESSAGE_ID = re.compile(r'^<[^<>\s@]+@[^<>\s@]+>$')
MESSAGE_IDS = re.compile(r'<[^<>\s@]+@[^<>\s@]+>')


def check_send_access(account):
    if not account.encrypted_credentials or account.requires_reauth:
        raise HTTPException(409, 'Reconnect Gmail before replying or forwarding.')
    try:
        scopes = set(json.loads(account.scopes))
    except (TypeError, ValueError):
        raise HTTPException(503, 'Stored Gmail permission information is invalid.') from None
    if not scopes & SEND_SCOPES:
        raise HTTPException(409, 'Gmail send permission is required. Reconnect Gmail.')


def source_message(db, user_id, account_id, message_id, lock=False):
    account = owned_account(db, user_id, account_id, lock=lock)
    check_send_access(account)
    message = db.query(EmailMessage).filter_by(account_id=account_id, id=message_id).first()
    if message is None:
        raise HTTPException(404, 'Message not found in this Gmail account.')
    thread = db.query(EmailThread).filter_by(account_id=account_id, id=message.thread_id).first()
    if thread is None:
        raise HTTPException(409, 'Conversation changed. Sync mail before replying.')
    return account, message, thread


def header(message, name):
    return next((str(item.get('value', '')).strip() for item in message.headers or []
                 if str(item.get('name', '')).lower() == name), '')


def addresses(values):
    return [email.lower() for _, email in getaddresses(values) if email and '@' in email]


def unique_addresses(values, self_address):
    found, result = set(), []
    for value in values:
        key = value.lower()
        if key != self_address and key not in found:
            result.append(value)
            found.add(key)
    return result


def reply_headers(message):
    original_id = header(message, 'message-id')
    if not MESSAGE_ID.fullmatch(original_id) or len(original_id) > 255:
        raise HTTPException(409, 'This message lacks a valid Message-ID. Sync mail or forward it instead.')
    prior = header(message, 'references')
    refs = MESSAGE_IDS.findall(prior) if len(prior) <= 4000 else []
    if not refs or refs[-1] != original_id:
        refs.append(original_id)
    refs = refs[-20:]
    return original_id, ' '.join(refs)


def reply_subject(subject):
    subject = subject.strip()
    if not subject or '\r' in subject or '\n' in subject:
        raise HTTPException(409, 'The original subject is unavailable. Sync mail before replying.')
    return subject if re.match(r'(?i)^re\s*:', subject) else f'Re: {subject}'


def forward_body(message):
    body = message.body_text or ''
    if not body and message.body_html:
        body = html_to_text(message.body_html[:100_000]).strip()
    body = body[:20_000]
    sent = datetime.fromtimestamp(message.internal_date / 1000, timezone.utc).strftime('%a, %d %b %Y %H:%M UTC')
    to = ', '.join(item.get('email', '') for item in message.to_addresses or [])
    return f'\n\n---------- Forwarded message ----------\nFrom: {message.from_address or "Unknown"}\nDate: {sent}\nSubject: {message.subject or "(No subject)"}\nTo: {to}\n\n{body}'


def prepare(db, user_id, account_id, message_id, mode):
    if mode not in ('reply', 'reply_all', 'forward'):
        raise HTTPException(422, 'Choose reply, reply-all, or forward.')
    account, message, thread = source_message(db, user_id, account_id, message_id)
    self_address = account.gmail_email.lower()
    reply_to = addresses([header(message, 'reply-to')])
    sender = reply_to or addresses([message.from_address or ''])
    original_to = [item['email'] for item in message.to_addresses or [] if item.get('email')]
    original_cc = [item['email'] for item in message.cc_addresses or [] if item.get('email')]
    if mode == 'forward':
        to, cc, subject, body = [], [], f'Fwd: {(message.subject or "(No subject)").strip()}', forward_body(message)
        in_reply_to, references = None, None
    else:
        in_reply_to, references = reply_headers(message)
        to = unique_addresses(sender if self_address not in sender else original_to, self_address)
        if not to:
            to = unique_addresses(original_to, self_address)
        if not to:
            raise HTTPException(409, 'No reply recipient is available. Forward this message instead.')
        cc = unique_addresses([*original_to, *original_cc], self_address) if mode == 'reply_all' else []
        cc = [item for item in cc if item not in set(to)]
        subject, body = reply_subject(message.subject or ''), ''
    original_files = db.query(EmailAttachment).filter_by(account_id=account_id, message_id=message_id).order_by(EmailAttachment.id).all()
    context = {'message_id': message.id, 'gmail_message_id': message.gmail_message_id,
               'thread_id': thread.gmail_thread_id, 'headers': message.headers,
               'from': message.from_address, 'to': message.to_addresses, 'cc': message.cc_addresses,
               'subject': message.subject, 'body_text': message.body_text, 'body_html': message.body_html,
               'attachments': [(item.id, item.filename, item.size_bytes) for item in original_files],
               'mode': mode}
    fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'mode': mode, 'to': to, 'cc': cc, 'subject': subject, 'body': body,
            'context_hash': fingerprint, 'in_reply_to': in_reply_to, 'references': references,
            'gmail_thread_id': thread.gmail_thread_id if mode != 'forward' else None,
            'original_attachments': len(original_files)}


def send(db, user_id, account_id, message_id, data, service=None, limiter=None):
    current = prepare(db, user_id, account_id, message_id, data.mode)
    if current['context_hash'] != data.context_hash:
        raise HTTPException(409, 'This conversation changed. Review the latest message before sending.')
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
        service = gmail_service.get_gmail_service(credentials.to_json())
    gate = limiter if limiter is not None else GmailRateLimiter()
    try:
        account, _, _ = source_message(db, user_id, account_id, message_id, lock=True)
        latest = prepare(db, user_id, account_id, message_id, data.mode)
        if latest['context_hash'] != data.context_hash:
            raise HTTPException(409, 'This conversation changed. Review it again before sending.')
        raw = gmail_service.build_raw(', '.join(data.to), latest['subject'], data.body,
                                      data.attachment.model_dump() if data.attachment else None,
                                      cc=', '.join(data.cc), in_reply_to=latest['in_reply_to'],
                                      references=latest['references'])
        payload = {'raw': raw}
        if latest['gmail_thread_id']:
            payload['threadId'] = latest['gmail_thread_id']
        gate.wait(account_id)
        result = service.users().messages().send(userId='me', body=payload).execute(num_retries=0)
        sent_id = result.get('id')
        if not isinstance(sent_id, str) or not sent_id:
            raise HTTPException(502, 'Gmail could not confirm sending. Check Sent before trying again.')
        account.next_sync_at = utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action=f'thread.{data.mode}',
                        resource_type='gmail_message', resource_id=sent_id, outcome='success'))
        db.commit()
        return {'message_id': sent_id, 'threaded': not latest['gmail_thread_id'] or
                result.get('threadId') == latest['gmail_thread_id']}
    except (HttpError, RedisError, OSError, OperationalError):
        db.rollback()
        raise HTTPException(503, 'Gmail could not confirm sending. Check Sent before trying again.') from None
