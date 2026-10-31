"""Canonical account-scoped API names alongside existing client-compatible URLs."""
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.mail_sync.service import owned_account
from app.features.mailbox import reader
from app.features.mailbox.actions import change_message
from app.features.mailbox.models import AiSuggestion, EmailMessage, EmailThread
from app.features.mailbox.schemas import MailPage

router = APIRouter(prefix='/accounts/{account_id}', tags=['account-mailbox'], dependencies=[Depends(private_response)])


class Toggle(BaseModel):
    enabled: bool = True


@router.post('/emails/{email_id}/read')
def read(account_id: int, email_id: int, request: Toggle | None = None,
         user=Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, email_id, read=request.enabled if request else True)


@router.post('/emails/{email_id}/star')
def star(account_id: int, email_id: int, request: Toggle | None = None,
         user=Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, email_id, starred=request.enabled if request else True)


@router.post('/emails/{email_id}/archive')
def archive(account_id: int, email_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, email_id, action='archive')


@router.get('/categories/{category}', response_model=MailPage)
def category(account_id: int, category: str, cursor: str | None = Query(default=None, max_length=1024),
             limit: int = Query(default=30, ge=1, le=100), user=Depends(get_current_user), db: Session = Depends(get_db)):
    labels = {'primary': 'CATEGORY_PERSONAL', 'promotions': 'CATEGORY_PROMOTIONS',
        'social': 'CATEGORY_SOCIAL', 'updates': 'CATEGORY_UPDATES', 'forums': 'CATEGORY_FORUMS',
        'spam': 'SPAM', 'trash': 'TRASH'}
    if category not in labels:
        raise HTTPException(404, 'Unknown mailbox category.')
    return reader.list_messages(db, user.id, account_id, label=labels[category], page_token=cursor, page_size=limit)


@router.get('/threads')
def threads(account_id: int, cursor: str | None = Query(default=None, max_length=1024),
            limit: int = Query(default=30, ge=1, le=100), user=Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user.id, account_id)
    scope = reader.scope_key(user.id, account_id, 'threads')
    query = db.query(EmailThread).filter_by(account_id=account_id)
    if cursor:
        date, row_id = reader.decode_cursor(cursor, scope)
        query = query.filter(or_(EmailThread.last_message_at < date,
            and_(EmailThread.last_message_at == date, EmailThread.id < row_id)))
    rows = query.order_by(EmailThread.last_message_at.desc(), EmailThread.id.desc()).limit(limit + 1).all()
    more, rows = len(rows) > limit, rows[:limit]
    counts = dict(db.query(EmailMessage.thread_id, func.count()).filter(EmailMessage.account_id == account_id,
        EmailMessage.thread_id.in_([row.id for row in rows])).group_by(EmailMessage.thread_id)) if rows else {}
    return {'items': [{'id': row.id, 'subject': row.subject or '', 'snippet': row.snippet or '',
        'last_message_at': row.last_message_at, 'message_count': counts.get(row.id, 0)} for row in rows],
        'next_cursor': reader.encode_cursor(SimpleNamespace(id=rows[-1].id, internal_date=rows[-1].last_message_at or 0), scope) if more else None}


@router.get('/ai/important', response_model=MailPage)
def important(account_id: int, cursor: str | None = Query(default=None, max_length=1024),
              user=Depends(get_current_user), db: Session = Depends(get_db)):
    return reader.list_messages(db, user.id, account_id, label='MYBOX', important_only=True, page_token=cursor)


@router.get('/ai/actions')
def actions(account_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user.id, account_id)
    latest = select(func.max(AiSuggestion.id)).where(AiSuggestion.user_id == user.id,
        AiSuggestion.account_id == account_id, AiSuggestion.operation == 'extract_actions').group_by(AiSuggestion.thread_id)
    rows = db.query(AiSuggestion).filter(AiSuggestion.id.in_(latest)).order_by(AiSuggestion.id.desc()).limit(100)
    return {'items': [{'thread_id': row.thread_id, 'suggestion_id': row.id, **action}
        for row in rows for action in row.result.get('actions', [])]}
