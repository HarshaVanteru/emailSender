"""User-authorized sends. Unknown outcomes can be reconciled, never re-sent."""
import base64
import hashlib
from email import message_from_bytes, policy

from fastapi import HTTPException

from app.core.time import utcnow
from app.features.google_login.accounts import credentials_for_account
from app.features.mail_sync.service import owned_account
from app.features.compose_email.thread_service import check_send_access, prepare
from app.integrations.gmail.adapter import GmailAdapter
from app.integrations.gmail.client import gmail_service
from app.workers.rate_limit import GmailRateLimiter
from app.workers import operations
from app.workers.operation_models import SendJob


def enqueue(db, user_id, account_id, operation, data, key):
    check_send_access(owned_account(db, user_id, account_id))
    if operation == 'thread':
        context = prepare(db, user_id, account_id, data['message_id'], data['mode'])
        if context['context_hash'] != data['context_hash']:
            raise HTTPException(409, 'Conversation changed. Review it again before sending.')
    rfc_id = '<' + hashlib.sha256(f'{account_id}:{key}'.encode()).hexdigest() + '@email-studio.invalid>'
    return operations.submit(db, 'send', user_id, account_id, operation, data, key, rfc_message_id=rfc_id)


def execute_job(db, row, data, service=None, limiter=None):
    credentials = credentials_for_account(db, row.user_id, row.account_id) if service is None else None
    adapter = GmailAdapter(service or gmail_service.get_gmail_service(credentials.to_json()))
    account = owned_account(db, row.user_id, row.account_id, lock=True)
    check_send_access(account)
    gate = limiter or GmailRateLimiter()
    if row.operation == 'draft':
        from app.features.drafts.service import draft_details, check_draft_access
        check_draft_access(account)
        gate.wait(account.id)
        original = adapter.draft(data['draft_id']).execute(num_retries=0)
        current = draft_details(original, account.gmail_email)
        if (current['content_hash'] != data['content_hash'] or not current['can_edit']):
            raise HTTPException(409, 'Gmail draft changed or cannot be fully reviewed. Open it again.')
        if not (current['to'] or current['cc'] or current['bcc']) or not current['subject'] or not current['body'].strip():
            raise HTTPException(422, 'Complete recipients, subject and message before sending.')
        raw = original['message']['raw']
        message = message_from_bytes(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)), policy=policy.default)
        row.rfc_message_id = str(message['Message-ID']) if message['Message-ID'] else None
        db.commit()  # Persist correlation before the irreversible call.
        request = adapter.send_draft(data['draft_id'])
    else:
        if row.operation == 'thread':
            context = prepare(db, row.user_id, row.account_id, data['message_id'], data['mode'])
            if context['context_hash'] != data['context_hash']:
                raise HTTPException(409, 'Conversation changed. Review it again before sending.')
            raw = gmail_service.build_raw(', '.join(data['to']), context['subject'], data['body'], data.get('attachment'),
                cc=', '.join(data.get('cc', [])), in_reply_to=context['in_reply_to'], references=context['references'],
                message_id=row.rfc_message_id)
            outgoing = {'raw': raw}
            if context['gmail_thread_id']:
                outgoing['threadId'] = context['gmail_thread_id']
        else:
            raw = gmail_service.build_raw(data.get('to'), data['subject'], data['body'], data.get('attachment'),
                cc=data.get('cc'), bcc=data.get('bcc'), body_html=data.get('body_html'),
                attachments=data.get('attachments'), message_id=row.rfc_message_id)
            outgoing = {'raw': raw}
        request = adapter.send(outgoing)
    gate.wait(account.id)
    result = request.execute(num_retries=0)
    if not isinstance(result.get('id'), str) or not result['id']:
        raise RuntimeError('unconfirmed_send')
    account = owned_account(db, row.user_id, row.account_id, lock=True)
    from app.features.google_login.accounts import persist_provider_refresh
    persist_provider_refresh(account, adapter.resource)
    account.next_sync_at = utcnow()
    return {'message_id': result['id'], 'threaded': row.operation != 'thread' or
            not context['gmail_thread_id'] or result.get('threadId') == context['gmail_thread_id'], 'status': 'success'}


def reconcile(db, user_id, account_id, job_id, service=None, limiter=None):
    row = operations.get_job(db, 'send', user_id, account_id, job_id)
    if row.status != 'unknown' or not row.rfc_message_id:
        return operations.payload(row)
    credentials = credentials_for_account(db, user_id, account_id) if service is None else None
    adapter = GmailAdapter(service or gmail_service.get_gmail_service(credentials.to_json()))
    (limiter or GmailRateLimiter()).wait(account_id)
    matches = adapter.list_messages(q=f'in:sent rfc822msgid:{row.rfc_message_id.strip("<>")}', maxResults=10).execute(num_retries=0)
    if matches.get('messages'):
        row.status = 'sent'
        row.result = {'message_id': matches['messages'][0]['id'], 'status': 'success'}
        row.completed_at, row.error_code, row.payload_ciphertext = utcnow(), None, None
        db.commit()
    # Absence does not prove non-delivery (indexing and provider delays).
    return operations.payload(row)
