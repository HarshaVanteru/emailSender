"""Reviewed reply and forward requests."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.features.drafts.schemas import DraftInput
from app.features.compose_email.schemas import EmailAttachment


class ThreadSend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['reply', 'reply_all', 'forward']
    context_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    to: list[EmailStr] = Field(min_length=1, max_length=50)
    cc: list[EmailStr] = Field(default_factory=list, max_length=50)
    body: str = Field(min_length=1, max_length=1_000_000)
    attachment: EmailAttachment | None = None

    @field_validator('attachment')
    @classmethod
    def safe_attachment(cls, value):
        return DraftInput.safe_attachment(value)

    @model_validator(mode='after')
    def valid_recipients(self):
        addresses = [str(item).lower() for item in [*self.to, *self.cc]]
        if len(addresses) > 50 or len(addresses) != len(set(addresses)):
            raise ValueError('Recipients must be unique and limited to 50.')
        if not self.body.strip():
            raise ValueError('Message body is required.')
        return self
