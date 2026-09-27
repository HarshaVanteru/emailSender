from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models.user
from app.controllers.ai_controller import router as ai_router
from app.controllers.gmail_controller import router as gmail_router
from app.core.database import Base, engine

Base.metadata.create_all(bind=engine)

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

app.include_router(gmail_router)
app.include_router(ai_router)

@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "emailSender API"}

DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "emailSender API is running", "docs": "/docs"}
