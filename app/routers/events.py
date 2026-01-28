import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
import aiosqlite

from app.database import get_db
from app.models.events import WebEvent, WebEventResponse, CLIEvent, CLIEventResponse
from app.services.slack import notify_prompt_copied, notify_cli_first_run

router = APIRouter()


@router.post("/events", response_model=WebEventResponse)
async def track_event(event: WebEvent, db: aiosqlite.Connection = Depends(get_db)):
    # Upsert user
    now = datetime.now(timezone.utc).isoformat()
    user_type = "web" if event.user_id.startswith("web_") else "cli"
    await db.execute(
        """INSERT INTO users (id, type, created_at, last_seen_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET last_seen_at = ?""",
        (event.user_id, user_type, now, now, now),
    )

    # Insert event
    cursor = await db.execute(
        "INSERT INTO events (event_type, user_id, session_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
        (event.event_type, event.user_id, event.session_id, json.dumps(event.data) if event.data else None, now),
    )
    await db.commit()

    # Slack notification for copy_prompt
    if event.event_type == "copy_prompt":
        version = (event.data or {}).get("prompt_version", "unknown")
        await notify_prompt_copied(event.session_id or "none", version, event.user_id)

    return WebEventResponse(
        success=True, event_id=cursor.lastrowid, session_id=event.session_id
    )


@router.post("/events/cli", response_model=CLIEventResponse)
async def track_cli_event(event: CLIEvent, db: aiosqlite.Connection = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()

    # Check if new user
    row = await db.execute_fetchall("SELECT id FROM users WHERE id = ?", (event.user_id,))
    is_new_user = len(row) == 0

    # Upsert user
    await db.execute(
        """INSERT INTO users (id, type, created_at, last_seen_at)
           VALUES (?, 'cli', ?, ?)
           ON CONFLICT(id) DO UPDATE SET last_seen_at = ?""",
        (event.user_id, now, now, now),
    )

    # Insert CLI event
    await db.execute(
        """INSERT INTO cli_events
           (user_id, session_id, command, profile, duration_ms, success, error_message, cli_version, os, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event.user_id, event.session_id, event.command, event.profile,
            event.duration_ms, event.success, event.error_message,
            event.cli_version, event.os, now,
        ),
    )
    await db.commit()

    if is_new_user:
        await notify_cli_first_run(event.user_id, event.command, event.cli_version)

    return CLIEventResponse(success=True)
