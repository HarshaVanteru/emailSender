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


@router.post('/reply', status_code=202)
def reply_suggestion(account_id: int, thread_id: int, request: ContextAiRequest,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.ai_assistant.jobs import enqueue
    from app.workers.operations import payload
    return payload(enqueue(db, user.id, account_id, thread_id, 'generate_reply', request))


@router.get('/summary', response_model=StoredSuggestion)
def summary(account_id: int, thread_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.ai_assistant.context_service import load_context, PROMPT_VERSION
    from app.core.config import AI_MODEL
    from app.workers.operations import fingerprint
    from app.features.mailbox.models import AiSuggestion
    from fastapi import HTTPException
    _, _, _, records = load_context(db, user.id, account_id, thread_id)
    digest = fingerprint({'source': {'conversation': records, 'user_instruction': '', 'selected_text': ''},
        'prompt_version': PROMPT_VERSION, 'model': AI_MODEL})
    row = db.query(AiSuggestion).filter_by(user_id=user.id, account_id=account_id, thread_id=thread_id,
        operation='summarize', input_hash=digest).order_by(AiSuggestion.id.desc()).first()
    if not row:
        raise HTTPException(404, 'Generate a fresh summary for this conversation.')
    return {'id': row.id, 'message_id': row.message_id, 'operation': row.operation,
            'result': row.result, 'created_at': row.created_at.isoformat()}


@router.post('/{operation}', status_code=202)
def create_suggestion(account_id: int, thread_id: int, operation: AiOperation,
                      request: ContextAiRequest, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    from app.features.ai_assistant.jobs import enqueue
    from app.workers.operations import payload
    return payload(enqueue(db, user.id, account_id, thread_id, operation, request))


@router.post('/jobs/{operation}', status_code=202)
def create_job(account_id: int, thread_id: int, operation: AiOperation, request: ContextAiRequest,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.ai_assistant.jobs import enqueue
    from app.workers.operations import payload
    return payload(enqueue(db, user.id, account_id, thread_id, operation, request))


@router.get('/jobs/{job_id}')
def job_status(account_id: int, thread_id: int, job_id: str,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.workers.operations import get_job, payload
    from fastapi import HTTPException
    row = get_job(db, 'ai', user.id, account_id, job_id)
    if row.thread_id != thread_id:
        raise HTTPException(404, 'AI job not found in this conversation.')
    return payload(row)
