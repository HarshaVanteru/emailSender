import base64
import json
from email.message import EmailMessage
from mimetypes import guess_type

from app.services.email_layout import reflow_email_body, render_email_html

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp
import httplib2

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
        return build("gmail", "v1", http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=30)))

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachment: dict | None = None,
        google_token: str | None = None,
    ):
        service = self.get_gmail_service(google_token)
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(reflow_email_body(body))
        message.add_alternative(render_email_html(body), subtype="html")

        if attachment:
            content_type = attachment.get("content_type") or (
                guess_type(attachment["filename"])[0] or "application/octet-stream"
            )
            maintype, subtype = content_type.split("/", 1)
            file_bytes = base64.b64decode(attachment["data"])
            message.add_attachment(
                file_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment["filename"],
            )

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return (
            service.users()
            .messages()
            .send(userId="me", body={"raw": encoded_message})
            .execute()
        )


gmail_service = GmailService()
