from pydantic import BaseModel
from typing import Optional


class PromptLatestResponse(BaseModel):
    version: str
    session_id: str
    content: str


class PromptVersionItem(BaseModel):
    version: str
    is_active: bool
    created_at: str


class PromptVersionsResponse(BaseModel):
    versions: list[PromptVersionItem]


class PromptCreateRequest(BaseModel):
    version: str
    content: str
    is_active: Optional[bool] = False
