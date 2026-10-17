from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AiOperation = Literal['summarize', 'generate_reply', 'rewrite', 'extract_actions', 'classify']


class ContextAiRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    instruction: str = Field(default='', max_length=2000)
    text: str = Field(default='', max_length=8000)
    message_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def check_rewrite_text(self):
        if self.text and not self.text.strip():
            raise ValueError('Text must not be blank.')
        return self


class ReplySuggestion(BaseModel):
    to: str = Field(max_length=320)
    subject: str = Field(max_length=998)
    body: str = Field(min_length=1, max_length=8000)


class ActionSuggestion(BaseModel):
    action: str = Field(min_length=1, max_length=600)
    owner: str | None = Field(default=None, max_length=200)
    due_date: str | None = Field(default=None, max_length=100)


class ContextAiOutput(BaseModel):
    summary: str | None = Field(default=None, max_length=3000)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    draft: ReplySuggestion | None = None
    rewritten_text: str | None = Field(default=None, max_length=8000)
    actions: list[ActionSuggestion] = Field(default_factory=list, max_length=12)
    category: Literal['work', 'personal', 'finance', 'travel', 'support', 'other'] | None = None
    priority: Literal['low', 'normal', 'high'] | None = None
    reason: str | None = Field(default=None, max_length=600)

    @field_validator('key_points')
    @classmethod
    def bounded_points(cls, values):
        if any(len(value) > 600 for value in values):
            raise ValueError('Key point is too long.')
        return values


class StoredSuggestion(BaseModel):
    id: int
    message_id: int | None = None
    operation: AiOperation
    result: ContextAiOutput
    created_at: str
