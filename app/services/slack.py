import httpx
import logging
from app.config import SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)


async def send_slack_notification(text: str, blocks: list | None = None):
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping notification")
        return

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Slack notification")


async def notify_prompt_copied(session_id: str, version: str, user_id: str):
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Prompt Copied"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Session:*\n`{session_id}`"},
                {"type": "mrkdwn", "text": f"*Version:*\n{version}"},
                {"type": "mrkdwn", "text": f"*User:*\n`{user_id[:16]}...`"},
            ],
        },
    ]
    await send_slack_notification("Prompt Copied", blocks)


async def notify_session_correlated(
    session_id: str, web_user_id: str, cli_user_id: str
):
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Journey Connected!"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "A website visitor has started using the CLI!",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Session:*\n`{session_id}`"},
                {"type": "mrkdwn", "text": f"*Web User:*\n`{web_user_id[:16]}...`"},
                {"type": "mrkdwn", "text": f"*CLI User:*\n`{cli_user_id[:16]}...`"},
            ],
        },
    ]
    await send_slack_notification("Journey Connected!", blocks)


async def notify_cli_first_run(user_id: str, command: str, cli_version: str | None):
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "New CLI User!"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*User:*\n`{user_id[:16]}...`"},
                {"type": "mrkdwn", "text": f"*First Command:*\n`{command}`"},
                {"type": "mrkdwn", "text": f"*CLI Version:*\n{cli_version or 'unknown'}"},
            ],
        },
    ]
    await send_slack_notification("New CLI User!", blocks)
