from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.features.google_login.user
import app.features.google_login.models
import app.features.mailbox.models
from app.features.ai_assistant.routes import router as ai_router
from app.features.google_login.routes import accounts_router, auth_router, legacy_router as gmail_router
from app.features.mail_sync.routes import router as sync_router
from app.features.mailbox.routes import router as mailbox_router
from app.features.drafts.routes import router as drafts_router
from app.features.compose_email.thread_routes import router as thread_send_router
from app.features.ai_assistant.context_routes import router as context_ai_router
from app.features.mail_sync.realtime import router as realtime_router
from app.features.mail_sync.push_routes import router as gmail_push_router

from app.features.profile.routes import router as profile_router
from app.features.compose_email.routes import router as compose_router

app = FastAPI(
    title="emailSender",
    description="FastAPI Backend for AI Email Studio with Feature-Based Architecture",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register APIs before the frontend's catch-all static mount. Keep legacy URLs
# during migration so installed builds and registered OAuth callbacks still work.
app.include_router(gmail_router, prefix="/api", include_in_schema=False)
app.include_router(ai_router, prefix="/api", include_in_schema=False)
app.include_router(gmail_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api", include_in_schema=False)
app.include_router(compose_router, prefix="/api", include_in_schema=False)
app.include_router(profile_router, prefix="/api/v1")
app.include_router(compose_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(sync_router, prefix="/api/v1")
app.include_router(mailbox_router, prefix="/api/v1")
app.include_router(drafts_router, prefix="/api/v1")
app.include_router(thread_send_router, prefix="/api/v1")
app.include_router(context_ai_router, prefix="/api/v1")
app.include_router(gmail_push_router, prefix="/api/v1")
app.include_router(realtime_router, prefix="/api/v1")


@app.get("/api/health", include_in_schema=False)
@app.get("/api/v1/health")
def health():
    return {"status": "healthy", "service": "emailSender API"}


DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
else:

    @app.get("/")
    def root():
        return {"message": "emailSender API is running", "docs": "/docs"}
