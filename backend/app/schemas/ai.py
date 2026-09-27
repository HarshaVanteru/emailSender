from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class GenerateEmailRequest(BaseModel):
    instruction: str
    messages: list[ChatMessage] | None = None


class GeneratedEmail(BaseModel):
    to: str = Field(default="", description="Recipient email address")
    subject: str = Field(default="", description="Email subject line")
    body: str = Field(default="", description="Full email body text")


class CopilotResponse(BaseModel):
    needs_clarification: bool = False
    question: str | None = None
    draft: GeneratedEmail | None = None
    message: str | None = None
