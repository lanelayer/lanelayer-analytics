from datetime import datetime, timezone
from fastapi import APIRouter, Depends
import aiosqlite

from app.database import get_db
from app.models.sessions import CorrelateRequest, CorrelateResponse
from app.services.slack import notify_session_correlated

router = APIRouter()


@router.post("/sessions/correlate", response_model=CorrelateResponse)
async def correlate_session(
    req: CorrelateRequest, db: aiosqlite.Connection = Depends(get_db)
):
    row = await db.execute_fetchall(
        "SELECT web_user_id FROM sessions WHERE id = ?", (req.session_id,)
    )
    if not row:
        return CorrelateResponse(success=False, correlated=False)

    web_user_id = row[0][0]
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        "UPDATE sessions SET cli_user_id = ?, correlated_at = ? WHERE id = ?",
        (req.cli_user_id, now, req.session_id),
    )
    await db.commit()

    if web_user_id:
        await notify_session_correlated(req.session_id, web_user_id, req.cli_user_id)

    return CorrelateResponse(
        success=True, correlated=True, web_user_id=web_user_id
    )
