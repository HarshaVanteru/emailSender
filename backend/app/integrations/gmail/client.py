import base64
import json
from contextvars import ContextVar
from email.message import EmailMessage
from mimetypes import guess_type

from app.features.compose_email.email_layout import reflow_email_body, render_email_html

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp
import httplib2

send_correlation = ContextVar('send_correlation', default=None)

from app.core.config import (
    GMAIL_SCOPES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)


class GmailService:
    def create_google_flow(self, scopes=None) -> Flow:
        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=scopes or GMAIL_SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI,
        )

    def exchange_google_code(self, flow: Flow, code: str):
        def record_granted_scopes(response):
            # Incremental/granular consent can return a superset or subset of
            # requested scopes. Track the actual grant on this session only;
            # each mailbox operation still checks its required permissions.
            granted = response.json().get("scope")
            if granted is not None:
                if not isinstance(granted, str) or not granted.strip():
                    raise ValueError("Invalid granted scope response")
                flow.oauth2session.scope = granted.split()
            return response
        flow.oauth2session.register_compliance_hook("access_token_response", record_granted_scopes)
        flow.fetch_token(code=code, timeout=15)
        return flow.credentials

    def get_gmail_service(self, google_token: str):
        if not google_token:
            raise ValueError(
                "Gmail credentials not provided. Please authenticate via /api/gmail/auth first."
            )

        data = json.loads(google_token)
        # Returning OAuth grants can omit refresh_token. Their fresh access token
        # is sufficient for profile verification before the stored token is merged.
        data.setdefault("refresh_token", None)
        credentials = Credentials.from_authorized_user_info(data)
        return build("gmail", "v1", http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=30), max_refresh_attempts=1))

    def build_raw(self, to: str | None, subject: str, body: str, attachment: dict | None = None,
                  draft: bool = False, cc: str | None = None, in_reply_to: str | None = None,
                  references: str | None = None, bcc: str | None = None,
                  body_html: str | None = None, attachments: list[dict] | None = None,
                  message_id: str | None = None) -> str:
        message = EmailMessage()
        if to:
            message["To"] = to
        if cc:
            message["Cc"] = cc
        if bcc:
            message["Bcc"] = bcc
        message["Subject"] = subject
        message_id = message_id or send_correlation.get()
        if message_id:
            message["Message-ID"] = message_id
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        if draft:
            message["X-Email-Studio-Draft"] = "1"
        message.set_content(reflow_email_body(body))
        from app.features.compose_email.rich_text import clean_html
        html, images = clean_html(body_html, inline_images=True) if body_html is not None else (render_email_html(body), [])
        message.add_alternative(html, subtype="html")
        html_part = message.get_payload()[-1]
        for cid, subtype, binary in images:
            html_part.add_related(binary, maintype="image", subtype=subtype, cid=f"<{cid}>")
        for attachment in ([attachment] if attachment else []) + (attachments or []):
            content_type = attachment.get("content_type") or (guess_type(attachment["filename"])[0] or "application/octet-stream")
            maintype, subtype = content_type.split("/", 1)
            message.add_attachment(base64.b64decode(attachment["data"], validate=True),
                                   maintype=maintype, subtype=subtype, filename=attachment["filename"])
        raw = message.as_bytes()
        if len(raw) > 36 * 1024 * 1024:
            raise ValueError("Message including inline images and attachments is too large.")
        return base64.urlsafe_b64encode(raw).decode()

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachment: dict | None = None,
        google_token: str | None = None,
        cc: str | None = None, bcc: str | None = None,
        body_html: str | None = None, attachments: list[dict] | None = None,
    ):
        service = self.get_gmail_service(google_token)
        return (
            service.users()
            .messages()
            .send(userId="me", body={"raw": self.build_raw(to, subject, body, attachment, cc=cc, bcc=bcc, body_html=body_html, attachments=attachments)})
            .execute(num_retries=0)
        )


gmail_service = GmailService()
