import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]

# Load environment variables from backend/.env
load_dotenv(BASE_DIR / ".env")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "mysql+pymysql://root:password@host.docker.internal:3306/email_sender"
)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY")
OAUTH_STATE_TTL_SECONDS = 600
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
GMAIL_PUSH_TOPIC = os.getenv("GMAIL_PUSH_TOPIC", "")
PUBSUB_PUSH_AUDIENCE = os.getenv("PUBSUB_PUSH_AUDIENCE", "")
PUBSUB_PUSH_SERVICE_ACCOUNT = os.getenv("PUBSUB_PUSH_SERVICE_ACCOUNT", "")
PUBSUB_SUBSCRIPTION = os.getenv("PUBSUB_SUBSCRIPTION", "")
SYNC_MAX_ATTEMPTS = max(1, int(os.getenv("SYNC_MAX_ATTEMPTS", "4")))
SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("SYNC_INTERVAL_SECONDS", "300")))
SYNC_RECONCILE_SECONDS = max(300, int(os.getenv("SYNC_RECONCILE_SECONDS", "86400")))
SYNC_TASK_TIME_LIMIT = max(60, int(os.getenv("SYNC_TASK_TIME_LIMIT", "1800")))
SYNC_LEASE_SECONDS = SYNC_TASK_TIME_LIMIT + 60
SYNC_REQUESTS_PER_SECOND = max(1, min(20, int(os.getenv("SYNC_REQUESTS_PER_SECOND", "10"))))
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

GMAIL_LEGACY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# All current Gmail features: mailbox reads/actions, drafts, replies, and sends.
# Modify covers readonly, compose, and send; request it once alongside identity.
GMAIL_SCOPES = [
    GMAIL_MODIFY_SCOPE,
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
]

MYBOX_ENABLED = os.getenv("MYBOX_ENABLED", "true").lower() == "true"
MYBOX_MODEL = os.getenv("MYBOX_MODEL", "openai/gpt-oss-120b")
