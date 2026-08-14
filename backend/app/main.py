from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.features.gmail.router import router as gmail_router
from app.features.ai.router import router as ai_router


app = FastAPI(
    title="emailSender",
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

@app.get("/")
def root():
    return {
        "message": "emailSender API is running"
    }
