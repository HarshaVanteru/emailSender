from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.features.gmail.oauth import (
    create_google_flow,
    save_credentials,
)
from app.features.gmail.service import get_gmail_service
from app.features.gmail.schemas import SendEmailRequest
from app.features.gmail.service import send_email
router = APIRouter(
    prefix="/api/gmail",
    tags=["Gmail"],
)


oauth_state = None
oauth_code_verifier = None


@router.get("/auth")
def gmail_auth():
    global oauth_state
    global oauth_code_verifier

    flow = create_google_flow()

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    oauth_state = state
    oauth_code_verifier = flow.code_verifier

    return RedirectResponse(authorization_url)


@router.get("/auth/google/callback")
def gmail_auth_callback(code: str, state: str):
    global oauth_state
    global oauth_code_verifier

    if not oauth_state or state != oauth_state:
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state",
        )

    flow = create_google_flow()

    flow.code_verifier = oauth_code_verifier

    flow.fetch_token(code=code)

    credentials = flow.credentials

    save_credentials(credentials)

    oauth_state = None
    oauth_code_verifier = None

    return {
        "message": "Gmail authentication successful",
    }

@router.get("/test")
def test_gmail():
    service = get_gmail_service()

    profile = service.users().getProfile(
        userId="me"
    ).execute()

    return {
        "email": profile["emailAddress"]
    }

@router.post("/send")
def send_gmail_email(request: SendEmailRequest):
    result = send_email(
        to=request.to,
        subject=request.subject,
        body=request.body,
        attachment=request.attachment.model_dump() if request.attachment else None,
    )

    return {
        "message": "Email sent successfully",
        "message_id": result["id"],
    }
