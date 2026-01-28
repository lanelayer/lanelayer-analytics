import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
import aiosqlite

from app.database import get_db

router = APIRouter()

DOC_BASE_URL = "https://lanelayer.com"

DOC_ROUTES = {
    "guide": "/guide-reference.html",
    "quickstart": "/build-first-lane.html",
    "kv-api": "/guide-reference.html#step-4-understanding-the-kv-api",
    "deployment": "/guide-reference.html#step-7-deploy-to-flyio",
    "terminology": "/terminology.html",
}


@router.get("/docs/{doc_id}")
async def track_doc_access(
    doc_id: str,
    session: str = Query(default=None),
    user: str = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Log the doc access event
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO events (event_type, user_id, session_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
        ("doc_access", user, session, json.dumps({"doc_id": doc_id}), now),
    )
    await db.commit()

    path = DOC_ROUTES.get(doc_id, "/")
    return RedirectResponse(url=f"{DOC_BASE_URL}{path}")
