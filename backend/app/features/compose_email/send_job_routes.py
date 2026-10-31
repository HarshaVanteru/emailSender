from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.compose_email.schemas import SendEmailRequest
from app.features.compose_email.thread_schemas import ThreadSend
from app.features.drafts.schemas import ReviewedDraftSend
from app.features.compose_email import send_jobs
from app.workers import operations

router = APIRouter(prefix='/accounts/{account_id}', tags=['send-jobs'], dependencies=[Depends(private_response)])
IdempotencyKey = Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)]


class ThreadReply(ThreadSend):
    message_id: int = Field(gt=0)


@router.post('/threads/{thread_id}/reply', status_code=202)
def thread_reply(account_id: int, thread_id: int, data: ThreadReply, idempotency_key: IdempotencyKey,
                 user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mailbox.repository import mailbox_repository
    message = mailbox_repository.get_message(db, user.id, account_id, data.message_id)
    if not message or message.thread_id != thread_id or data.mode not in ('reply', 'reply_all'):
        raise HTTPException(404, 'Reply source not found in this conversation.')
    return operations.payload(send_jobs.enqueue(db, user.id, account_id, 'thread', data.model_dump(), idempotency_key))


@router.post('/emails/send', status_code=202)
def compose(account_id: int, data: SendEmailRequest, idempotency_key: IdempotencyKey,
            user=Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.payload(send_jobs.enqueue(db, user.id, account_id, 'compose', data.model_dump(exclude={'account_id'}), idempotency_key))


@router.post('/messages/{message_id}/send-jobs', status_code=202)
def reply(account_id: int, message_id: int, data: ThreadSend, idempotency_key: IdempotencyKey,
          user=Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.payload(send_jobs.enqueue(db, user.id, account_id, 'thread', {**data.model_dump(), 'message_id': message_id}, idempotency_key))


@router.post('/drafts/{draft_id}/send-jobs', status_code=202)
def draft(account_id: int, draft_id: str, data: ReviewedDraftSend, idempotency_key: IdempotencyKey,
          user=Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.payload(send_jobs.enqueue(db, user.id, account_id, 'draft', {'draft_id': draft_id, 'content_hash': data.content_hash}, idempotency_key))


@router.get('/send-jobs/{job_id}')
def status(account_id: int, job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.payload(operations.get_job(db, 'send', user.id, account_id, job_id))


@router.get('/send-jobs')
def recent(account_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.service import owned_account
    from app.workers.operation_models import SendJob
    owned_account(db, user.id, account_id)
    return [operations.payload(row) for row in db.query(SendJob).filter_by(user_id=user.id, account_id=account_id).order_by(SendJob.created_at.desc()).limit(20)]


@router.post('/send-jobs/{job_id}/reconcile')
def reconcile(account_id: int, job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return send_jobs.reconcile(db, user.id, account_id, job_id)
