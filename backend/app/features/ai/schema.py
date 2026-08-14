from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    role: str
    content: str


class GenerateEmailRequest(BaseModel):
    instruction: str
    messages: list[ChatMessage] = []


class GeneratedEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str
    subject: str
    body: str
