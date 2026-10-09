from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services import mailbox_reader


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(tags=["mailbox"], dependencies=[Depends(private_response)])
AccountId = Annotated[int, Query(gt=0)]
PageToken = Annotated[str | None, Query(max_length=1024)]


@router.get("/emails")
@router.get("/search")
def list_emails(account_id: AccountId, label: Annotated[str | None, Query(max_length=128)] = None,
                unread: bool | None = None, q: Annotated[str, Query(max_length=200)] = "",
                page_size: Annotated[int, Query(ge=1, le=100)] = 30, page_token: PageToken = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.list_messages(db, user.id, account_id, label=label, unread=unread, q=q,
                                         page_size=page_size, page_token=page_token)


@router.get("/emails/{message_id}")
def get_email(message_id: int, account_id: AccountId,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.read_message(db, user.id, account_id, message_id)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, account_id: AccountId,
               page_size: Annotated[int, Query(ge=1, le=25)] = 10, page_token: PageToken = None,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.read_thread(db, user.id, account_id, thread_id, page_size, page_token)


@router.get("/accounts/{account_id}/labels")
def labels(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.list_labels(db, user.id, account_id)
