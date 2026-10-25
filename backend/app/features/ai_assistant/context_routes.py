from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.google_login.user import User
from app.features.ai_assistant.context_schemas import AiOperation, ContextAiRequest, StoredSuggestion
from app.features.ai_assistant.context_service import generate, list_suggestions


router = APIRouter(prefix='/accounts/{account_id}/threads/{thread_id}/ai', tags=['context-ai'],
                   dependencies=[Depends(private_response)])


@router.get('', response_model=list[StoredSuggestion])
def suggestions(account_id: int, thread_id: int, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return list_suggestions(db, user.id, account_id, thread_id)


@router.post('/{operation}', response_model=StoredSuggestion, status_code=201)
def create_suggestion(account_id: int, thread_id: int, operation: AiOperation,
                      request: ContextAiRequest, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    return generate(db, user.id, account_id, thread_id, operation, request)
