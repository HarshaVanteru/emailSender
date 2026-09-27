from pydantic import BaseModel, EmailStr


class EmailAttachment(BaseModel):
    filename: str
    content_type: str
    data: str

class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    attachment: EmailAttachment | None = None

class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    signature: str | None = None
    preferences: str | None = None
    bio: str | None = None
