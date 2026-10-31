from pydantic import BaseModel, Field
from typing import Literal


class Recipient(BaseModel):
    name: str
    email: str


class AttachmentMetadata(BaseModel):
    id: int
    filename: str
    mime_type: str
    size_bytes: int


class MailSummary(BaseModel):
    id: int
    account_id: int
    thread_id: int
    from_address: str
    subject: str
    snippet: str
    internal_date: int
    labels: list[str]
    has_attachments: bool
    ai_importance: str | None = None
    ai_is_spam: bool | None = None
    ai_category: str | None = None
    ai_reason: str | None = None


class MailDetail(MailSummary):
    to_addresses: list[Recipient]
    cc_addresses: list[Recipient]
    body_text: str | None
    body_html: str | None
    attachments: list[AttachmentMetadata]


class HistoricalStatus(BaseModel):
    status: Literal['idle', 'pending', 'ready', 'completed', 'failed', 'expired'] = 'idle'
    session_id: str | None = None


class MailPage(BaseModel):
    items: list[MailSummary]
    next_page_token: str | None
    next_cursor: str | None = None
    has_more_local: bool = False
    historical_sync: HistoricalStatus = Field(default_factory=HistoricalStatus)


class ThreadPage(BaseModel):
    id: int
    account_id: int
    subject: str
    items: list[MailDetail]
    next_page_token: str | None


class MailLabel(BaseModel):
    id: str
    name: str
    type: str
