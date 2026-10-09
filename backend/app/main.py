from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models.user
import app.models.connection
import app.models.mailbox
from app.controllers.ai_controller import router as ai_router
from app.controllers.gmail_controller import accounts_router, auth_router, router as gmail_router
from app.controllers.sync_controller import router as sync_router
from app.controllers.mailbox_controller import router as mailbox_router

app = FastAPI(
    title="emailSender",
    description="FastAPI Backend for AI Email Studio with Layered Architecture",
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
app.include_router(ai_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(sync_router, prefix="/api/v1")
app.include_router(mailbox_router, prefix="/api/v1")


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
