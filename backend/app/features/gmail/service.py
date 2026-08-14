import base64
from email.message import EmailMessage
from mimetypes import guess_type
from pathlib import Path
import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


BASE_DIR = Path(__file__).resolve().parents[3]
TOKEN_FILE = BASE_DIR / "credentials" / "token.json"


def get_gmail_service():
    with open(TOKEN_FILE, "r") as file:
        token_data = json.load(file)

    credentials = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data.get("scopes"),
    )

    service = build(
        "gmail",
        "v1",
        credentials=credentials,
    )

    return service

def send_email(
    to: str,
    subject: str,
    body: str,
    attachment: dict | None = None,
):

    service = get_gmail_service()

    message = EmailMessage()

    message["To"] = to
    message["Subject"] = subject

    message.set_content(body)

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

    encoded_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    result = service.users().messages().send(
        userId="me",
        body={
            "raw": encoded_message
        }
    ).execute()

    return result
