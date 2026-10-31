import base64
import hashlib
import json
from urllib.parse import urlencode, urlsplit

import requests
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import FRONTEND_URL, GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE, GMAIL_READ_SCOPE, GMAIL_SCOPES, GOOGLE_REDIRECT_URI, OAUTH_STATE_TTL_SECONDS
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, create_session, oauth2_scheme
from app.core.time import utcnow
from app.features.google_login.user import User
from app.features.google_login.repository import user_repository
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.adapter import GmailAdapter
from app.features.google_login.models import ConnectedAccount, UserSession, LoginIdentity
from app.features.google_login import accounts as account_service, oauth_state
from app.features.mail_sync.service import READ_SCOPES
legacy_router = APIRouter(prefix="/gmail", tags=["gmail"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])

accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])

@legacy_router.get("/auth")
@auth_router.get("/google")
def gmail_auth(renew_consent: bool = False, mailbox_access: bool = False, modify_access: bool = False,
               draft_access: bool = False,
               db: Session = Depends(get_db)):
    return authorization_response(db, renew_consent)


def authorization_response(db, renew_consent=False, *, user_id=None, session_id=None, account_id=None):
    # Every new connection requests all current Gmail features. Keep the legacy
    # feature flags in the signature for existing frontend/reconnect URLs.
    scopes = list(GMAIL_SCOPES)
    try:
        state, browser, verifier = oauth_state.create_attempt(
            db, scopes, user_id=user_id, session_id=session_id, account_id=account_id)
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
    response = JSONResponse({"authorization_url": auth_url}) if user_id else RedirectResponse(url=auth_url)
    response.set_cookie(oauth_state.cookie_name(state), browser, max_age=OAUTH_STATE_TTL_SECONDS,
                        httponly=True, secure=urlsplit(GOOGLE_REDIRECT_URI or "").scheme == "https",
                        samesite="lax", path="/api")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@accounts_router.post("/google/connect")
def connect_account(user: User = Depends(get_current_user), token: str = Depends(oauth2_scheme),
                    db: Session = Depends(get_db)):
    from jose import jwt
    from app.core.security import signing_key
    # Upgrade a legacy bearer to a persisted session for the connection attempt.
    payload = jwt.decode(token, signing_key(), algorithms=["HS256"]) if token else {}
    session = db.get(UserSession, payload["sid"]) if payload.get("sid") else create_session(db, user)
    return authorization_response(db, True, user_id=user.id, session_id=session.id)


@accounts_router.post("/{account_id}/reconnect")
def reconnect_account(account_id: int, user: User = Depends(get_current_user),
                      token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from app.features.mail_sync.service import owned_account
    from jose import jwt
    from app.core.security import signing_key
    owned_account(db, user.id, account_id)
    payload = jwt.decode(token, signing_key(), algorithms=["HS256"]) if token else {}
    session = db.get(UserSession, payload["sid"]) if payload.get("sid") else create_session(db, user)
    return authorization_response(db, True, user_id=user.id, session_id=session.id, account_id=account_id)


@legacy_router.get("/auth/google/callback")
@auth_router.get("/google/callback")
@accounts_router.get("/google/callback")
def gmail_auth_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db)
):
    try:
        attempt = oauth_state.consume_attempt(db, state, request.cookies.get(oauth_state.cookie_name(state)))
    except (ValueError, InvalidToken):
        raise HTTPException(400, "Invalid or expired OAuth state. Start a new Gmail connection.") from None
    if attempt.user_id:
        initiating_session = db.get(UserSession, attempt.session_id)
        if (not initiating_session or initiating_session.user_id != attempt.user_id
                or initiating_session.revoked_at or initiating_session.expires_at <= utcnow()):
            raise HTTPException(401, "The initiating session expired. Sign in and reconnect.")
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
                mailbox = GmailAdapter(gmail_service.get_gmail_service(credentials.to_json())).profile().execute(num_retries=0)
                if mailbox["emailAddress"].lower() != email:
                    raise HTTPException(400, "Google identity does not match this Gmail mailbox.")
                history_id = mailbox.get("historyId")
            subject = info.get("sub")
            if subject is not None and (not isinstance(subject, str) or not subject or len(subject) > 255):
                raise HTTPException(400, "Invalid Google identity.")
            if attempt.user_id:
                session = db.query(UserSession).filter_by(id=attempt.session_id).populate_existing().with_for_update().first()
                if not session or session.revoked_at or session.expires_at <= utcnow():
                    raise HTTPException(401, 'The initiating session expired. Sign in and reconnect.')
                if not subject:
                    raise HTTPException(400, "Google did not return a stable identity.")
                user = db.get(User, attempt.user_id)
            else:
                identity = db.get(LoginIdentity, subject) if subject else None
                user = db.get(User, identity.user_id) if identity else user_repository.get_by_email(db, email)
                if not user:
                    user = User(email=email, name=info.get("name"))
                    db.add(user)
                    db.flush()
                if subject and not identity:
                    db.add(LoginIdentity(google_sub=subject, user_id=user.id))
            account = account_service.save_connection(db, user, credentials, history_id,
                email=email, google_sub=subject, account_id=attempt.account_id)
            if scopes & READ_SCOPES:
                from app.features.mail_sync.jobs import activate_mailbox
                background_tasks.add_task(activate_mailbox, user.id, account.id)
        except account_service.OfflineAccessRequired:
            db.rollback()
            # Offer an explicit retry without creating a session or widening scopes.
            recovery = {"auth": "offline_access_required"}
            if attempt.user_id:
                recovery['connection'] = 'account'
                if attempt.account_id is not None:
                    recovery['account_id'] = str(attempt.account_id)
            for scope, flag in (
                (GMAIL_READ_SCOPE, "mailbox_access"),
                (GMAIL_MODIFY_SCOPE, "modify_access"),
                (GMAIL_COMPOSE_SCOPE, "draft_access"),
            ):
                if scope in attempt.scopes:
                    recovery[flag] = "true"
            response = RedirectResponse(f"{FRONTEND_URL.rstrip('/')}/#" + urlencode(recovery))
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            # Provider failures may contain tokens, codes and secrets. Never echo them.
            raise HTTPException(502, "Gmail connection failed. Please start a new connection.") from None
        else:
            session = create_session(db, user)
            access_token = create_access_token(data={"sub": user.email, "sid": session.id})
            # Fragments are not sent to servers, access logs, or in Referer headers.
            response = RedirectResponse(f"{FRONTEND_URL.rstrip('/')}/#" + urlencode({"token": access_token, "auth": "success"}))
    response.delete_cookie(oauth_state.cookie_name(state), path="/api")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@accounts_router.get("")
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = db.query(ConnectedAccount).filter(ConnectedAccount.user_id == current_user.id).all()
    return [{"id": account.id, "email": account.gmail_email,
             "is_connected": bool(account.encrypted_credentials and not account.requires_reauth),
             "requires_reauth": account.requires_reauth,
             "mailbox_access": bool(set(json.loads(account.scopes or "[]")) & READ_SCOPES),
             "modify_access": bool(set(json.loads(account.scopes or "[]")) & {GMAIL_MODIFY_SCOPE, "https://mail.google.com/"}),
             "draft_access": bool(set(json.loads(account.scopes or "[]")) & {GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE, "https://mail.google.com/"}),
             "send_access": bool(set(json.loads(account.scopes or "[]")) & {GMAIL_COMPOSE_SCOPE, GMAIL_MODIFY_SCOPE, "https://www.googleapis.com/auth/gmail.send", "https://mail.google.com/"}),
             "sync_paused": account.sync_paused, "last_synced_at": account.last_synced_at,
             "next_sync_at": account.next_sync_at, "mail_import_complete": account.mail_import_complete} for account in accounts]


@accounts_router.delete("/{account_id}")
def disconnect_gmail(account_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account_service.disconnect_account(db, current_user, account_id)
    return {"status": "disconnected"}


@accounts_router.get('/{account_id}')
def account_details(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.service import owned_account
    account = owned_account(db, user.id, account_id)
    return {'id': account.id, 'email': account.gmail_email,
        'is_connected': bool(account.encrypted_credentials and not account.requires_reauth),
        'requires_reauth': account.requires_reauth, 'initial_sync_days': account.initial_sync_days,
        'initial_sync_completed': account.mail_import_complete}


@auth_router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Revoke all sessions, including a pending OAuth connection from this user.
    db.query(UserSession).filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": utcnow()})
    db.commit()
    return {"status": "signed_out"}

