from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class GenerateEmailRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    messages: list[ChatMessage] | None = Field(default=None, max_length=12)


class GeneratedEmail(BaseModel):
    to: str = Field(default="", description="Recipient email address")
    subject: str = Field(default="", description="Email subject line")
    body: str = Field(default="", description="Full email body text")


class CopilotResponse(BaseModel):
    needs_clarification: bool = False
    question: str | None = None
    draft: GeneratedEmail | None = None
    message: str | None = None
