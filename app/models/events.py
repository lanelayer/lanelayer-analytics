from pydantic import BaseModel
from typing import Optional


class WebEvent(BaseModel):
    event_type: str
    user_id: str
    session_id: Optional[str] = None
    data: Optional[dict] = None


class WebEventResponse(BaseModel):
    success: bool
    event_id: int
    session_id: Optional[str] = None


class CLIEvent(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    command: str
    profile: Optional[str] = None
    duration_ms: Optional[int] = None
    success: Optional[bool] = None
    error_message: Optional[str] = None
    cli_version: Optional[str] = None
    os: Optional[str] = None


class CLIEventResponse(BaseModel):
    success: bool
