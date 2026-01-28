from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from app.database import get_db
from app.models.prompts import (
    PromptLatestResponse,
    PromptVersionsResponse,
    PromptVersionItem,
    PromptCreateRequest,
)
from app.utils.id_generator import generate_session_id

router = APIRouter()


@router.get("/prompt/latest", response_model=PromptLatestResponse)
async def get_latest_prompt(db: aiosqlite.Connection = Depends(get_db)):
    row = await db.execute_fetchall(
        "SELECT version, content FROM prompt_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    )
    if not row:
        raise HTTPException(status_code=404, detail="No active prompt version found")

    version = row[0][0]
    content = row[0][1]
    session_id = generate_session_id()

    # Create session record
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO sessions (id, prompt_version, created_at) VALUES (?, ?, ?)",
        (session_id, version, now),
    )
    await db.commit()

    # Inject session ID into prompt content
    tagged_content = f"{content}\n\n---\nLaneLayer Prompt {version} | Session: {session_id}"

    return PromptLatestResponse(
        version=version, session_id=session_id, content=tagged_content
    )


@router.get("/prompt/versions", response_model=PromptVersionsResponse)
async def list_prompt_versions(db: aiosqlite.Connection = Depends(get_db)):
    rows = await db.execute_fetchall(
        "SELECT version, is_active, created_at FROM prompt_versions ORDER BY id DESC"
    )
    versions = [
        PromptVersionItem(version=r[0], is_active=bool(r[1]), created_at=r[2])
        for r in rows
    ]
    return PromptVersionsResponse(versions=versions)


@router.post("/prompt/versions")
async def create_prompt_version(
    req: PromptCreateRequest, db: aiosqlite.Connection = Depends(get_db)
):
    now = datetime.now(timezone.utc).isoformat()

    if req.is_active:
        await db.execute("UPDATE prompt_versions SET is_active = 0")

    await db.execute(
        "INSERT INTO prompt_versions (version, content, is_active, created_at) VALUES (?, ?, ?, ?)",
        (req.version, req.content, req.is_active, now),
    )
    await db.commit()
    return {"success": True, "version": req.version}
