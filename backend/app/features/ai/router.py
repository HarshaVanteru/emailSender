from fastapi import APIRouter

from app.features.ai.schema import GenerateEmailRequest, GeneratedEmail
from app.features.ai.service import generate_email


router = APIRouter(
    prefix="/api/ai",
    tags=["AI"],
)


@router.post("/generate-email", response_model=GeneratedEmail)
def generate_email_endpoint(request: GenerateEmailRequest):
    return generate_email(
        instruction=request.instruction,
        history=request.messages,
    )
