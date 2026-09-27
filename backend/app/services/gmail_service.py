import base64
import json
from email.message import EmailMessage
from mimetypes import guess_type

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import (
    GMAIL_SCOPES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)


class GmailService:
    def create_google_flow(self) -> Flow:
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
            scopes=GMAIL_SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI,
        )

    def get_gmail_service(self, google_token: str):
        if not google_token:
            raise ValueError("Gmail credentials not provided. Please authenticate via /api/gmail/auth first.")

        token_data = json.loads(google_token)
        credentials = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data["token_uri"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=token_data.get("scopes"),
        )
        return build("gmail", "v1", credentials=credentials)

    def send_email(self, to: str, subject: str, body: str, attachment: dict | None = None, google_token: str | None = None):
        service = self.get_gmail_service(google_token)
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        if attachment:
            content_type = attachment.get("content_type") or (guess_type(attachment["filename"])[0] or "application/octet-stream")
            maintype, subtype = content_type.split("/", 1)
            file_bytes = base64.b64decode(attachment["data"])
            message.add_attachment(
                file_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment["filename"],
            )

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()

gmail_service = GmailService()
