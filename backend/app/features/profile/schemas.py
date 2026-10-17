from pydantic import BaseModel


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    signature: str | None = None
    preferences: str | None = None
    bio: str | None = None
