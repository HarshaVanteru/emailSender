import base64
import binascii
import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, field_validator, model_validator

MAX_FILES_BYTES = 25 * 1024 * 1024
email_address = TypeAdapter(EmailStr)


class EmailAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=128)
    data: str = Field(max_length=MAX_FILES_BYTES * 4 // 3 + 8)


def validate_attachment(value, limit=5 * 1024 * 1024):
    if value is None:
        return value
    if any(character in value.filename for character in "\r\n"):
        raise ValueError("Invalid attachment filename.")
    if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value.content_type):
        raise ValueError("Invalid attachment content type.")
    try:
        if len(base64.b64decode(value.data, validate=True)) > limit:
            raise ValueError("Attachment exceeds the size limit.")
    except binascii.Error:
        raise ValueError("Invalid attachment encoding.") from None
    return value


class ComposeContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str | None = None
    cc: str = Field(default="", max_length=16000)
    bcc: str = Field(default="", max_length=16000)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=1_000_000)
    body_html: str | None = Field(default=None, max_length=32 * 1024 * 1024)
    attachment: EmailAttachment | None = None  # Legacy single-file clients.
    attachments: list[EmailAttachment] = Field(default_factory=list, max_length=20)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def safe_addresses(cls, value):
        if value is None or not value.strip():
            return None if value is None else ""
        if len(value) > 16000 or "\r" in value or "\n" in value:
            raise ValueError("Invalid recipients.")
        addresses = value.split(",")
        if len(addresses) > 100 or any(not address.strip() for address in addresses):
            raise ValueError("Use up to 100 comma-separated email addresses.")
        return ", ".join(str(email_address.validate_python(address.strip())) for address in addresses)

    @field_validator("subject")
    @classmethod
    def safe_subject(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("Subject must be one line.")
        return value

    @field_validator("attachment")
    @classmethod
    def safe_attachment(cls, value):
        return validate_attachment(value)

    @field_validator("attachments")
    @classmethod
    def safe_attachments(cls, values):
        for value in values:
            validate_attachment(value, MAX_FILES_BYTES)
        return values

    @field_validator("body_html")
    @classmethod
    def safe_html(cls, value):
        if value is not None:
            from app.features.compose_email.rich_text import clean_html
            value, _ = clean_html(value)
        return value

    @model_validator(mode="after")
    def total_size(self):
        files = self.attachments + ([self.attachment] if self.attachment else [])
        from app.features.compose_email.rich_text import clean_html
        _, images = clean_html(self.body_html, inline_images=True) if self.body_html else ("", [])
        if len(files) > 20 or sum(len(base64.b64decode(item.data)) for item in files) + sum(len(binary) for _, _, binary in images) > MAX_FILES_BYTES:
            raise ValueError("Use at most 20 files totaling 25 MB.")
        if sum(len((value or "").split(",")) if value else 0 for value in (self.to, self.cc, self.bcc)) > 100:
            raise ValueError("Use at most 100 recipients in total.")
        return self


class SendEmailRequest(ComposeContent):
    account_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def complete_message(self):
        if not (self.to or self.cc or self.bcc) or not self.subject.strip() or not self.body.strip():
            raise ValueError("Complete recipients, subject, and message before sending.")
        return self
