from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.workers import operations

from app.core.security import get_current_user
from app.features.google_login.user import User
from app.features.ai_assistant.schemas import CopilotResponse, GenerateEmailRequest
from app.features.ai_assistant.service import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])

@router.post("/generate-email", status_code=202)
def generate_email_endpoint(request: GenerateEmailRequest, current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    data = {'request': request.model_dump(), 'profile_version': operations.fingerprint({
        'name': current_user.name, 'bio': current_user.bio, 'preferences': current_user.preferences,
        'signature': current_user.signature})}
    key = operations.fingerprint({'user': current_user.id, **data})
    return operations.payload(operations.submit(db, 'ai', current_user.id, None, 'write', data, key, thread_id=0))


@router.get('/jobs/{job_id}')
def job_status(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.payload(operations.get_job(db, 'ai', current_user.id, None, job_id))
