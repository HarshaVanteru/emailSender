from pydantic import BaseModel, ConfigDict, Field

from app.features.compose_email.schemas import ComposeContent


class DraftInput(ComposeContent):
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


class ReviewedDraftSend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str = Field(min_length=64, max_length=64)
