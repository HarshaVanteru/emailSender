import base64
import hashlib
from urllib.parse import urlencode, urlsplit

import requests
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import FRONTEND_URL, GMAIL_READ_SCOPE, GMAIL_SCOPES, GOOGLE_REDIRECT_URI, OAUTH_STATE_TTL_SECONDS
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.schemas.gmail import SendEmailRequest, ProfileUpdateRequest
from app.services.gmail_service import gmail_service
from app.models.connection import ConnectedAccount
from app.services import account_service, oauth_state
router = APIRouter(prefix="/gmail", tags=["gmail"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])

accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])

@router.get("/auth")
@auth_router.get("/google")
def gmail_auth(renew_consent: bool = False, mailbox_access: bool = False, db: Session = Depends(get_db)):
    scopes = [*GMAIL_SCOPES, GMAIL_READ_SCOPE] if mailbox_access else GMAIL_SCOPES
    try:
        state, browser, verifier = oauth_state.create_attempt(db, scopes)
    except (ValueError, TypeError):
        raise HTTPException(503, "Configure the server's token encryption key before connecting Gmail.") from None
    flow = gmail_service.create_google_flow(scopes=scopes)
    flow.code_verifier = verifier
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    options = {"prompt": "consent"} if renew_consent else {}
    auth_url, _ = flow.authorization_url(
        state=state, code_challenge=challenge, code_challenge_method="S256",
        access_type="offline",
        include_granted_scopes="true", **options,
    )
    response = RedirectResponse(url=auth_url)
    response.set_cookie(oauth_state.cookie_name(state), browser, max_age=OAUTH_STATE_TTL_SECONDS,
                        httponly=True, secure=urlsplit(GOOGLE_REDIRECT_URI or "").scheme == "https",
                        samesite="lax", path="/api")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/auth/google/callback")
@auth_router.get("/google/callback")
def gmail_auth_callback(
    request: Request,
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db)
):
    try:
        attempt = oauth_state.consume_attempt(db, state, request.cookies.get(oauth_state.cookie_name(state)))
    except (ValueError, InvalidToken):
        raise HTTPException(400, "Invalid or expired OAuth state. Start a new Gmail connection.") from None
    if error or not code:
        response = RedirectResponse(f"{FRONTEND_URL.rstrip('/')}/#auth=cancelled")
    else:
        try:
            flow = gmail_service.create_google_flow(scopes=attempt.scopes)
            flow.code_verifier = attempt.verifier
            credentials = gmail_service.exchange_google_code(flow, code)
            info_response = requests.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"}, timeout=15,
            )
            info_response.raise_for_status()
            info = info_response.json()
            if info.get("email_verified") is not True or not info.get("email"):
                raise HTTPException(400, "Google did not return a verified email address.")
            email = info["email"].lower()
            history_id = None
            scopes = set(credentials.granted_scopes or credentials.scopes or [])
            if scopes & account_service.PROFILE_SCOPES:
                mailbox = gmail_service.get_gmail_service(credentials.to_json()).users().getProfile(userId="me").execute()
                if mailbox["emailAddress"].lower() != email:
                    raise HTTPException(400, "Google identity does not match this Gmail mailbox.")
                history_id = mailbox.get("historyId")
            user = user_repository.get_by_email(db, email)
            if not user:
                user = User(email=email, name=info.get("name"))
                db.add(user)
                db.flush()
            account_service.save_connection(db, user, credentials, history_id)
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            # Provider failures may contain tokens, codes and secrets. Never echo them.
            raise HTTPException(502, "Gmail connection failed. Please start a new connection.") from None
        access_token = create_access_token(data={"sub": user.email})
        # Fragments are not sent to servers, access logs, or in Referer headers.
        response = RedirectResponse(f"{FRONTEND_URL.rstrip('/')}/#" + urlencode({"token": access_token, "auth": "success"}))
    response.delete_cookie(oauth_state.cookie_name(state), path="/api")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = account_service.find_account(db, current_user)
    return {
        "email": current_user.email,
        "name": current_user.name,
        "signature": current_user.signature,
        "preferences": current_user.preferences,
        "bio": current_user.bio,
        "is_connected": bool(account and account.encrypted_credentials and not account.requires_reauth),
        "requires_reauth": bool(account and account.requires_reauth),
    }


@accounts_router.get("")
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = db.query(ConnectedAccount).filter(ConnectedAccount.user_id == current_user.id).all()
    return [{"id": account.id, "email": account.gmail_email,
             "is_connected": bool(account.encrypted_credentials and not account.requires_reauth),
             "requires_reauth": account.requires_reauth,
             "sync_paused": account.sync_paused, "last_synced_at": account.last_synced_at,
             "next_sync_at": account.next_sync_at} for account in accounts]


@accounts_router.delete("/{account_id}")
def disconnect_gmail(account_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account_service.disconnect_account(db, current_user, account_id)
    return {"status": "disconnected"}

@router.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    if request.name is not None: current_user.name = request.name
    if request.signature is not None: current_user.signature = request.signature
    if request.preferences is not None: current_user.preferences = request.preferences
    if request.bio is not None: current_user.bio = request.bio
    user_repository.update(db, current_user)
    return {"message": "Profile updated successfully"}

@router.post("/send")
def send_gmail_email(request: SendEmailRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    credentials = account_service.credentials_for_user(db, current_user)
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
            google_token=credentials.to_json(),
        )
        return {"status": "success", "message_id": result["id"]}
    except Exception:
        raise HTTPException(status_code=502, detail="Gmail could not confirm delivery. Check Sent in Gmail before trying again.") from None
