from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import FRONTEND_URL
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.schemas.gmail import SendEmailRequest, ProfileUpdateRequest
from app.services.gmail_service import gmail_service
import requests
router = APIRouter(prefix="/api/gmail", tags=["gmail"])

oauth_state = {}

@router.get("/auth")
def gmail_auth(user_email: str | None = None):
    flow = gmail_service.create_google_flow()

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )

    # Store the state, user email, and PKCE code verifier
    oauth_state[state] = {
        "user_email": user_email,
        "code_verifier": flow.code_verifier,
    }

    return RedirectResponse(url=auth_url)


@router.get("/auth/google/callback")
def gmail_auth_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db)
):
    # Get and remove the stored OAuth state
    oauth_data = oauth_state.pop(state, None)

    if not oauth_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state"
        )

    # Create the same OAuth flow
    flow = gmail_service.create_google_flow()

    # Restore the PKCE code verifier
    flow.code_verifier = oauth_data["code_verifier"]

    # Exchange authorization code for tokens
    flow.fetch_token(code=code)

    credentials = flow.credentials

    service = gmail_service.get_gmail_service(
        credentials.to_json()
    )

    user_info = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={
            "Authorization": f"Bearer {credentials.token}"
        }
    ).json()

    email = user_info["email"]

    user = user_repository.get_by_email(db, email)

    if not user:
        user = User(email=email)
        user_repository.create(db, user)

    user.google_token = credentials.to_json()
    user_repository.update(db, user)

    access_token = create_access_token(
        data={"sub": user.email}
    )

    return RedirectResponse(
        url=f"{FRONTEND_URL}/?token={access_token}&auth=success"
    )
@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "name": current_user.name,
        "signature": current_user.signature,
        "preferences": current_user.preferences,
        "is_connected": bool(current_user.google_token),
    }

@router.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    if request.name is not None: current_user.name = request.name
    if request.signature is not None: current_user.signature = request.signature
    if request.preferences is not None: current_user.preferences = request.preferences
    user_repository.update(db, current_user)
    return {"message": "Profile updated successfully"}

@router.post("/send")
def send_gmail_email(request: SendEmailRequest, current_user: User = Depends(get_current_user)):
    if not current_user.google_token:
        raise HTTPException(status_code=401, detail="Google token not found.")
    try:
        attachment_dict = None
        if request.attachment:
            attachment_dict = {
                "filename": request.attachment.filename,
                "content_type": request.attachment.content_type,
                "data": request.attachment.data
            }
        result = gmail_service.send_email(
            to=request.to,
            subject=request.subject,
            body=request.body,
            attachment=attachment_dict,
            google_token=current_user.google_token,
        )
        return {"status": "success", "message_id": result["id"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to send email: {e!s}")
