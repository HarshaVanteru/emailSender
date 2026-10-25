from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.google_login.user import User
from app.features.compose_email.thread_schemas import ThreadSend
from app.features.compose_email.thread_service import prepare, send


router = APIRouter(prefix='/accounts/{account_id}/messages/{message_id}', tags=['thread-compose'],
                   dependencies=[Depends(private_response)])


@router.get('/compose')
def compose_context(account_id: int, message_id: int, mode: Literal['reply', 'reply_all', 'forward'] = Query(),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return prepare(db, user.id, account_id, message_id, mode)


@router.post('/send')
def send_reviewed(account_id: int, message_id: int, data: ThreadSend,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return send(db, user.id, account_id, message_id, data)
