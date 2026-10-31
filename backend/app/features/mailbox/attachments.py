"""On-demand attachment bytes. Never render provider MIME types inline."""
import base64
from pathlib import PurePosixPath
from urllib.parse import quote
from fastapi import HTTPException
from fastapi.responses import Response
from app.features.mailbox.repository import mailbox_repository
from app.features.mailbox.models import EmailMessage
from app.features.mail_sync.service import owned_account, check_read_access
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.adapter import GmailAdapter
from app.workers.rate_limit import GmailRateLimiter

MAX_BYTES = 25 * 1024 * 1024


def find_part(part, part_id, depth=0):
    if depth > 30:
        raise ValueError('MIME depth exceeded')
    if part.get('partId') == part_id:
        return part.get('body', {}).get('data')
    for child in part.get('parts', []):
        data = find_part(child, part_id, depth + 1)
        if data is not None:
            return data
    return None


def download(db, user_id, account_id, attachment_id, service=None, limiter=None):
    part = mailbox_repository.get_attachment(db, user_id, account_id, attachment_id)
    if part is None:
        raise HTTPException(404, 'Attachment not found.')
    check_read_access(owned_account(db, user_id, account_id))
    if part.size_bytes > MAX_BYTES:
        raise HTTPException(413, 'Attachment exceeds the 25 MB download limit.')
    message = db.query(EmailMessage).filter_by(id=part.message_id, account_id=account_id).one()
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
        service = gmail_service.get_gmail_service(credentials.to_json())
    adapter = GmailAdapter(service)
    try:
        (limiter or GmailRateLimiter()).wait(account_id)
        if part.gmail_attachment_id:
            encoded = adapter.attachment(message.gmail_message_id, part.gmail_attachment_id).execute(num_retries=0)['data']
        else:
            raw = adapter.message(message.gmail_message_id).execute(num_retries=0)
            encoded = find_part(raw.get('payload', {}), part.mime_part_id)
        if not isinstance(encoded, str) or len(encoded) > MAX_BYTES * 4 // 3 + 8:
            raise ValueError('Invalid attachment content')
        binary = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if len(binary) > MAX_BYTES:
            raise ValueError('Attachment exceeds limit')
    except Exception:
        raise HTTPException(502, 'Attachment could not be retrieved safely. Refresh the mailbox and try again.') from None
    filename = PurePosixPath((part.filename or 'attachment').replace('\\', '/')).name
    filename = ''.join(char for char in filename if ord(char) >= 32 and ord(char) != 127)[:255] or 'attachment'
    return Response(binary, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
