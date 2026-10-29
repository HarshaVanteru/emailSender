from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.google_login.user import User
from app.features.mailbox.schemas import MailDetail, MailLabel, MailPage, ThreadPage
from app.features.mailbox import reader as mailbox_reader
from app.features.mailbox.actions import change_message


router = APIRouter(tags=["mailbox"], dependencies=[Depends(private_response)])
AccountId = Annotated[int, Query(gt=0)]
PageToken = Annotated[str | None, Query(max_length=1024)]


class MailChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: bool | None = None
    starred: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.read is None and self.starred is None:
            raise ValueError("Choose read or starred.")
        return self


@router.get("/emails", response_model=MailPage)
@router.get("/search", response_model=MailPage)
def list_emails(account_id: AccountId, label: Annotated[str | None, Query(max_length=128)] = None,
                importance: Literal["critical", "high", "normal", "low"] | None = None,
                unread: bool | None = None, q: Annotated[str, Query(max_length=200)] = "",
                page_size: Annotated[int, Query(ge=1, le=100)] = 30, page_token: PageToken = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.list_messages(db, user.id, account_id, label=label, unread=unread, q=q,
                                         page_size=page_size, page_token=page_token, importance=importance)


@router.get("/emails/{message_id}", response_model=MailDetail)
def get_email(message_id: int, account_id: AccountId,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.read_message(db, user.id, account_id, message_id)


@router.get("/threads/{thread_id}", response_model=ThreadPage)
def get_thread(thread_id: int, account_id: AccountId,
               page_size: Annotated[int, Query(ge=1, le=25)] = 10, page_token: PageToken = None,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.read_thread(db, user.id, account_id, thread_id, page_size, page_token)


@router.get("/accounts/{account_id}/labels", response_model=list[MailLabel])
def labels(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mailbox_reader.list_labels(db, user.id, account_id)


@router.patch("/emails/{message_id}", response_model=MailDetail)
def update_email(message_id: int, account_id: AccountId, change: MailChange,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, message_id, read=change.read, starred=change.starred)


@router.post("/emails/{message_id}/archive", response_model=MailDetail)
def archive_email(message_id: int, account_id: AccountId,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, message_id, action="archive")


@router.delete("/emails/{message_id}", response_model=MailDetail)
def trash_email(message_id: int, account_id: AccountId,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return change_message(db, user.id, account_id, message_id, action="trash")


@router.get("/accounts/{account_id}/mybox-status")
def mybox_status(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.core import config
    from app.features.mail_sync.service import owned_account
    from app.features.mailbox.models import EmailMessage, MessageTriage
    from sqlalchemy import func
    owned_account(db, user.id, account_id)
    incoming = db.query(EmailMessage).filter(EmailMessage.account_id == account_id,
        mailbox_reader.primary_message())
    states = dict(incoming.join(MessageTriage, MessageTriage.message_id == EmailMessage.id).with_entities(
        MessageTriage.state, func.count()).group_by(MessageTriage.state).all())
    return {"enabled": config.MYBOX_ENABLED, "configured": bool(config.GROQ_API_KEY),
            "pending": incoming.count() - states.get("succeeded", 0) - states.get("failed", 0),
            "failed": states.get("failed", 0)}


@router.post("/accounts/{account_id}/mybox-retry")
def retry_mybox(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.service import owned_account, utcnow
    from app.features.mailbox.models import MessageTriage
    owned_account(db, user.id, account_id)
    from app.features.mailbox.models import EmailMessage
    eligible = db.query(EmailMessage.id).filter(EmailMessage.account_id == account_id, mailbox_reader.primary_message())
    count = db.query(MessageTriage).filter_by(account_id=account_id, state="failed").filter(
        MessageTriage.message_id.in_(eligible)).update(
        {"state": "retry", "attempts": 0, "available_at": utcnow(), "updated_at": utcnow()}, synchronize_session=False)
    db.commit()
    return {"queued": count}
