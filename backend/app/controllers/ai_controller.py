from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.ai import GeneratedEmail, GenerateEmailRequest
from app.services.ai_service import ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"])

@router.post("/generate-email", response_model=GeneratedEmail)
def generate_email_endpoint(request: GenerateEmailRequest, current_user: User = Depends(get_current_user)):
    return ai_service.generate_email(
        instruction=request.instruction,
        history=request.messages,
        name=current_user.name,
        signature=current_user.signature,
        preferences=current_user.preferences,
    )
