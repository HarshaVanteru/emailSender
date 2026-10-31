"""Gmail-backed drafts. Sending requires an exact reviewed MIME fingerprint."""
import base64
import binascii
import hashlib
import json
from email import message_from_bytes, policy
from email.utils import getaddresses

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError

from app.core.config import GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE
from app.features.mailbox.models import AuditLog
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.adapter import GmailAdapter
from app.core.token_crypto import encrypt, decrypt
from cryptography.fernet import InvalidToken
from app.integrations.gmail.text import html_to_text
from app.features.mail_sync.service import owned_account, utcnow
from app.workers.rate_limit import GmailRateLimiter

COMPOSE_SCOPES = {GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE, "https://mail.google.com/"}
MAX_RAW_BYTES = 36 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def check_draft_access(account):
    if not account.encrypted_credentials or account.requires_reauth:
        raise HTTPException(409, "Reconnect Gmail before working with drafts.")
    try:
        scopes = set(json.loads(account.scopes))
    except (ValueError, TypeError):
        raise HTTPException(503, "Stored Gmail permission information is invalid.") from None
    if not scopes & COMPOSE_SCOPES:
        raise HTTPException(409, "Gmail draft permission is required. Connect with draft_access=true.")


def provider_error(exc):
    if isinstance(exc, HttpError):
        if exc.resp.status == 404:
            return HTTPException(404, "This Gmail draft was not found. Refresh your draft list.")
        if exc.resp.status in (401, 403):
            return HTTPException(409, "Gmail rejected this draft action. Check your connection and permissions.")
    return HTTPException(503, "Gmail could not confirm this draft action. Check Gmail before trying again.")


def provider_id(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise HTTPException(502, "Gmail returned an invalid draft identifier. Refresh your draft list.")
    return value


def draft_details(result, account_email=None):
    draft_id = provider_id(result.get("id"))
    encoded = result.get("message", {}).get("raw")
    if not isinstance(encoded, str) or len(encoded) > MAX_RAW_BYTES * 4 // 3 + 8:
        raise HTTPException(502, "Gmail draft content is unavailable or too large to preview.")
    try:
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(502, "Gmail draft content could not be read.") from None
    if len(raw) > MAX_RAW_BYTES:
        raise HTTPException(502, "Gmail draft is too large to preview.")
    message = message_from_bytes(raw, policy=policy.default)
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    text = plain.get_content() if plain else ""
    if not plain and html:
        text = html_to_text(html.get_content()).strip()
    body_html = html.get_content() if html else None
    for inline in message.walk():
        cid = str(inline.get("Content-ID", "")).strip("<>")
        if cid and inline.get_content_type() in {"image/png", "image/jpeg", "image/gif", "image/webp"} and body_html:
            data = base64.b64encode(inline.get_payload(decode=True) or b"").decode()
            body_html = body_html.replace(f"cid:{cid}", f"data:{inline.get_content_type()};base64,{data}")
    attachments = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.get_filename():
            binary = part.get_payload(decode=True) or b""
            attachments.append({"filename": part.get_filename() or "attachment", "content_type": part.get_content_type(),
                                "size_bytes": len(binary), "data": base64.b64encode(binary).decode()
                                if len(binary) <= MAX_ATTACHMENT_BYTES else None})
    recipients = str(message.get("To", ""))
    cc = str(message.get("Cc", ""))
    bcc = str(message.get("Bcc", ""))
    addresses = getaddresses([recipients])
    senders = getaddresses(message.get_all("From", []))
    sender_matches = (not message.get("From") or (
        account_email and len(senders) == 1
        and senders[0][1].casefold() == account_email.casefold()))
    app_draft = message.get('X-Email-Studio-Draft') == '1'
    editable = (bool(plain) and (app_draft or not html) and (app_draft or len(addresses) <= 1)
                and (app_draft or not addresses or addresses[0][1] == recipients)
                and (app_draft or (not cc and not bcc)) and not message.get('Reply-To') and sender_matches
                and not message.get('In-Reply-To') and not message.get('References')
                and all(len(message.get_all(name, [])) <= 1 for name in ("To", "Cc", "Bcc", "Subject", "From"))
                and (app_draft or len(attachments) <= 1) and all(item["data"] is not None for item in attachments))
    return {"id": draft_id, "to": recipients, "cc": cc, "bcc": bcc,
            "subject": str(message.get("Subject", "")),
            "body": text, "body_html": body_html if app_draft else None, "attachments": attachments, "can_edit": editable,
            "content_hash": hashlib.sha256(raw).hexdigest()}


def get_service(db, user_id, account_id, service):
    account = owned_account(db, user_id, account_id)
    check_draft_access(account)
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
        return gmail_service.get_gmail_service(credentials.to_json())
    return service


def get_draft(db, user_id, account_id, draft_id, service=None, limiter=None):
    service = get_service(db, user_id, account_id, service)
    gate = limiter or GmailRateLimiter()
    try:
        gate.wait(account_id)
        result = GmailAdapter(service).draft(draft_id).execute(num_retries=0)
    except (HttpError, RedisError, OSError) as exc:
        raise provider_error(exc) from None
    if result.get("id") != draft_id:
        raise HTTPException(502, "Gmail returned a different draft. Refresh your draft list.")
    account = owned_account(db, user_id, account_id)
    return draft_details(result, account.gmail_email)


def list_drafts(db, user_id, account_id, page_token=None, service=None, limiter=None):
    if page_token:
        try:
            cursor = json.loads(decrypt(page_token, ttl=3600))
            if cursor['user_id'] != user_id or cursor['account_id'] != account_id or cursor['kind'] != 'drafts':
                raise ValueError()
            page_token = cursor['provider_token']
        except (InvalidToken, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Invalid or expired draft page cursor for this account.') from None
    service = get_service(db, user_id, account_id, service)
    gate = limiter or GmailRateLimiter()
    try:
        gate.wait(account_id)
        result = GmailAdapter(service).list_drafts(page_token).execute(num_retries=0)
        items = []
        for draft in result.get("drafts", [])[:20]:
            draft_id = provider_id(draft.get("id"))
            gate.wait(account_id)
            details = GmailAdapter(service).draft_metadata(draft_id).execute(num_retries=0)
            if details.get("id") != draft_id:
                raise HTTPException(502, "Gmail returned an inconsistent draft list. Refresh it.")
            message = details.get("message", {})
            headers = {item.get("name", "").lower(): item.get("value", "") for item in message.get("payload", {}).get("headers", [])}
            items.append({"id": draft_id, "to": headers.get("to", ""), "subject": headers.get("subject", ""),
                          "snippet": message.get("snippet", "")})
    except (HttpError, RedisError, OSError) as exc:
        raise provider_error(exc) from None
    token = result.get('nextPageToken')
    cursor = encrypt(json.dumps({'kind': 'drafts', 'user_id': user_id, 'account_id': account_id,
                                  'provider_token': token})) if token else None
    return {"items": items, "next_page_token": cursor}


def save_draft(db, user_id, account_id, data, draft_id=None, service=None, limiter=None):
    service = get_service(db, user_id, account_id, service)
    gate = limiter or GmailRateLimiter()
    if draft_id and not data.content_hash:
        raise HTTPException(422, "Open and review the latest Gmail draft before updating it.")
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_draft_access(account)
        if draft_id:
            current = get_draft(db, user_id, account_id, draft_id, service, gate)
            if current["content_hash"] != data.content_hash:
                raise HTTPException(409, "This Gmail draft changed elsewhere. Reload it before saving.")
            if not current["can_edit"]:
                raise HTTPException(409, "This Gmail draft has content the editor cannot safely preserve. Open it in Gmail instead.")
        attachment = data.attachment.model_dump() if data.attachment else None
        if attachment and len(attachment["data"]) > MAX_ATTACHMENT_BYTES * 4 // 3 + 8:
            raise HTTPException(413, "Attachments must be 5 MB or smaller.")
        raw = gmail_service.build_raw(data.to, data.subject, data.body, attachment, draft=True,
                                           cc=data.cc, bcc=data.bcc, body_html=data.body_html,
                                           attachments=[item.model_dump() for item in data.attachments])
        gate.wait(account_id)
        result = GmailAdapter(service).save_draft(raw, draft_id).execute(num_retries=0)
        new_id = provider_id(result.get("id"))
        if draft_id and new_id != draft_id:
            raise HTTPException(502, "Gmail returned a different draft. Refresh your drafts.")
        account.next_sync_at = utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="draft.update" if draft_id else "draft.create",
                        resource_type="gmail_draft", resource_id=new_id, outcome="success"))
        db.commit()
        return get_draft(db, user_id, account_id, new_id, service, gate)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    except (HttpError, RedisError, OSError, OperationalError) as exc:
        db.rollback()
        raise provider_error(exc) from None


def _send_draft(db, user_id, account_id, draft_id, content_hash, service=None, limiter=None):
    service = get_service(db, user_id, account_id, service)
    gate = limiter or GmailRateLimiter()
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_draft_access(account)
        current = get_draft(db, user_id, account_id, draft_id, service, gate)
        if current["content_hash"] != content_hash:
            raise HTTPException(409, "This Gmail draft changed elsewhere. Review it again before sending.")
        if not current["can_edit"]:
            raise HTTPException(409, "This Gmail draft cannot be fully reviewed here. Open it in Gmail instead.")
        if not (current["to"] or current["cc"] or current["bcc"]) or not current["subject"] or not current["body"].strip():
            raise HTTPException(422, "Complete the recipient, subject and body before sending.")
        gate.wait(account_id)
        result = GmailAdapter(service).send_draft(draft_id).execute(num_retries=0)
        message_id = result.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise HTTPException(502, "Gmail could not confirm delivery. Check Sent before trying again.")
        account.next_sync_at = utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="draft.send",
                        resource_type="gmail_message", resource_id=message_id, outcome="success"))
        db.commit()
        return {"message_id": message_id}
    except (HttpError, RedisError, OSError, OperationalError) as exc:
        db.rollback()
        raise provider_error(exc) from None


def discard_draft(db, user_id, account_id, draft_id, content_hash, service=None, limiter=None):
    service = get_service(db, user_id, account_id, service)
    gate = limiter or GmailRateLimiter()
    try:
        owned_account(db, user_id, account_id, lock=True)
        current = get_draft(db, user_id, account_id, draft_id, service, gate)
        if current["content_hash"] != content_hash:
            raise HTTPException(409, "This draft changed elsewhere. Reload it before discarding.")
        gate.wait(account_id)
        GmailAdapter(service).delete_draft(draft_id).execute(num_retries=0)
        db.add(AuditLog(user_id=user_id, account_id=account_id, action="draft.discard",
                        resource_type="gmail_draft", resource_id=draft_id, outcome="success"))
        db.commit()
    except (HttpError, RedisError, OSError, OperationalError) as exc:
        db.rollback()
        raise provider_error(exc) from None


def send_draft(db, user_id, account_id, draft_id, content_hash, service=None, limiter=None):
    check_draft_access(owned_account(db, user_id, account_id))
    from app.features.compose_email.inline_receipt import receipt
    with receipt(db, user_id, account_id, 'legacy_draft', {'draft_id': draft_id, 'content_hash': content_hash}) as record:
        result = _send_draft(db, user_id, account_id, draft_id, content_hash, service, limiter)
        record.update(result)
        return result
