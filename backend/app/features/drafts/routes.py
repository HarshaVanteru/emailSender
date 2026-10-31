from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.google_login.user import User
from app.features.drafts.schemas import DraftInput, ReviewedDraftSend
from app.features.drafts.service import get_draft, list_drafts, save_draft, send_draft, discard_draft

router = APIRouter(prefix="/accounts/{account_id}/drafts", tags=["drafts"], dependencies=[Depends(private_response)])
DraftId = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


@router.get("")
def drafts(account_id: int, page_token: Annotated[str | None, Query(max_length=1024)] = None,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_drafts(db, user.id, account_id, page_token)


@router.post("", status_code=201)
def create_draft(account_id: int, data: DraftInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_draft(db, user.id, account_id, data)


@router.get("/{draft_id}")
def draft(account_id: int, draft_id: DraftId, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_draft(db, user.id, account_id, draft_id)


@router.put("/{draft_id}")
@router.patch("/{draft_id}")
def update_draft(account_id: int, draft_id: DraftId, data: DraftInput,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_draft(db, user.id, account_id, data, draft_id)


@router.post("/{draft_id}/send")
def send_reviewed(account_id: int, draft_id: DraftId, data: ReviewedDraftSend,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return send_draft(db, user.id, account_id, draft_id, data.content_hash)


@router.delete("/{draft_id}", status_code=204)
def discard(account_id: int, draft_id: DraftId, data: ReviewedDraftSend,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    discard_draft(db, user.id, account_id, draft_id, data.content_hash)
    return Response(status_code=204)
