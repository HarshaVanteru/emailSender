from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.features.google_login.user import User
from app.features.google_login import accounts as account_service
from app.features.compose_email.schemas import SendEmailRequest
from app.integrations.gmail.client import gmail_service
from app.features.compose_email.inline_receipt import tracked_send

router = APIRouter(prefix="/gmail", tags=["compose"])

@router.post("/send")
def send_gmail_email(request: SendEmailRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    credentials = (account_service.credentials_for_account(db, current_user.id, request.account_id)
                   if request.account_id else account_service.credentials_for_user(db, current_user))
    try:
        attachment_dict = None
        if request.attachment:
            attachment_dict = {
                "filename": request.attachment.filename,
                "content_type": request.attachment.content_type,
                "data": request.attachment.data
            }
        account_id = request.account_id or account_service.find_account(db, current_user).id
        result = tracked_send(db, current_user.id, account_id, request.model_dump(), lambda: gmail_service.send_email(
            to=request.to,
            subject=request.subject,
            body=request.body,
            attachment=attachment_dict,
            google_token=credentials.to_json(),
            cc=request.cc, bcc=request.bcc, body_html=request.body_html,
            attachments=[item.model_dump() for item in request.attachments],
        ))
        return {"status": "success", "message_id": result["id"]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=502, detail="Gmail could not confirm delivery. Check Sent in Gmail before trying again.") from None
