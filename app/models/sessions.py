from pydantic import BaseModel
from typing import Optional


class CorrelateRequest(BaseModel):
    session_id: str
    cli_user_id: str


class CorrelateResponse(BaseModel):
    success: bool
    correlated: bool
    web_user_id: Optional[str] = None
