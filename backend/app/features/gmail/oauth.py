from google_auth_oauthlib.flow import Flow

from pathlib import Path

from app.core.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GMAIL_SCOPES,
)

TOKEN_FILE = Path("credentials/token.json")

def create_google_flow() -> Flow:
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

def save_credentials(credentials):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    TOKEN_FILE.write_text(
        credentials.to_json(),
        encoding="utf-8",
    )