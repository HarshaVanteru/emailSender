from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class GenerateEmailRequest(BaseModel):
    instruction: str
    messages: list[ChatMessage] | None = None

class GeneratedEmail(BaseModel):
    to: str
    subject: str
    body: str
