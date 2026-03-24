#!/usr/bin/env python3
"""
Simple HTTP server with health endpoint and submission handler using aiohttp
"""

import aiohttp
from aiohttp import web
from datetime import datetime, timezone
import os
import json
import logging
import asyncio

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def health(request):
    return web.json_response(
        {
            "status": "OK",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "sample-python",
            "version": "1.0.0",
        }
    )


async def submit_handler(request):
    """
    Handle raw data submissions from core-lane.

    This endpoint receives raw binary data (application/octet-stream) with
    optional metadata passed via X- prefixed HTTP headers.
    """
    try:
        # Read raw binary data
        data = await request.read()

        # Extract metadata from headers
        forwarded_from = request.headers.get("X-Forwarded-From")
        content_type = request.headers.get("X-Content-Type")
        user = request.headers.get("X-User")
        timestamp = request.headers.get("X-Timestamp")

        logger.info(
            f"Received {len(data)} bytes from {forwarded_from or 'unknown source'}"
        )

        if forwarded_from:
            logger.info(f"Source: {forwarded_from}")
        if user:
            logger.info(f"User: {user}")
        if timestamp:
            logger.info(f"Timestamp: {timestamp}")

        # Process the raw data
        # Data can be any format: binary, text, JSON string, etc.

        # If X-Content-Type indicates JSON, try to parse it
        if content_type == "application/json":
            try:
                json_data = json.loads(data.decode("utf-8"))
                logger.info(f"Parsed JSON data: {json.dumps(json_data, indent=2)}")
                # Process JSON data as needed
                process_json_data(json_data, user, timestamp)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to parse JSON data: {e}")
                # Continue processing as raw data
                process_raw_data(data, forwarded_from, user)
        else:
            # Process raw binary data
            process_raw_data(data, forwarded_from, user)

        # Store submission metadata in K/V store to confirm connectivity
        await kv_set(
            f"submissions/{timestamp or 'latest'}",
            json.dumps(
                {
                    "user": user or "anonymous",
                    "bytes": len(data),
                    "source": forwarded_from,
                }
            ),
        )
        await kv_set("last_submission", user or "anonymous")

        return web.json_response(
            {
                "status": "ok",
                "message": "Submission processed successfully",
                "bytes_received": len(data),
            },
            status=200,
        )
    except Exception as e:
        logger.exception("Unexpected error processing submission")
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def process_raw_data(data: bytes, source: str = None, user: str = None):
    """Process raw binary data."""
    logger.info(f"Processing {len(data)} bytes of raw data")
    # Add your data processing logic here
    # This is where you handle the raw binary data


def process_json_data(json_data: dict, user: str = None, timestamp: str = None):
    """Process JSON data (when X-Content-Type indicates JSON)."""
    logger.info(f"Processing JSON data for user: {user}")
    # Add your JSON processing logic here
    # This is where you handle structured JSON data


# =============================================================================
# K/V Storage API
# =============================================================================
# These helper functions provide access to the ephemeral key-value store.
# In dev/test mode, this store resets when the environment restarts.
# In production, the K/V store provides persistent state for your derived lane.

# Internal URL for container-to-container communication (Traefik: 8080/kv, Direct: 3000/kv)
KV_BASE_URL = os.environ.get("KV_URL", "http://kv-service:3000/kv")

# Module-level session for connection reuse (aiohttp best practice)
_kv_session: aiohttp.ClientSession | None = None


async def _get_kv_session() -> aiohttp.ClientSession:
    """Get or create the shared aiohttp session for K/V operations."""
    global _kv_session
    if _kv_session is None or _kv_session.closed:
        _kv_session = aiohttp.ClientSession()
    return _kv_session


async def kv_close_session() -> None:
    """Close the K/V session. Call this on application shutdown."""
    global _kv_session
    if _kv_session and not _kv_session.closed:
        await _kv_session.close()
        _kv_session = None


async def kv_get(key: str) -> bytes | None:
    """
    Read a value from the K/V store.

    Args:
        key: The key to read (e.g., "user_count" or "users/alice/balance")

    Returns:
        The value as bytes, or None if the key doesn't exist.
    """
    try:
        session = await _get_kv_session()
        async with session.get(f"{KV_BASE_URL}/{key}") as resp:
            if resp.status == 200:
                return await resp.read()
            elif resp.status == 404:
                return None
            else:
                logger.warning(f"K/V GET {key} failed: HTTP {resp.status}")
                return None
    except Exception:
        logger.exception(f"K/V GET {key} error")
        return None


async def kv_set(key: str, value: bytes | str) -> bool:
    """
    Write a value to the K/V store.

    Args:
        key: The key to write (e.g., "user_count" or "users/alice/balance")
        value: The value to store (bytes or string)

    Returns:
        True if successful, False otherwise.
    """
    try:
        if isinstance(value, str):
            value = value.encode("utf-8")

        session = await _get_kv_session()
        async with session.post(
            f"{KV_BASE_URL}/{key}",
            data=value,
            headers={"Content-Type": "application/octet-stream"},
        ) as resp:
            if resp.status == 200:
                logger.info(f"K/V SET {key} ({len(value)} bytes)")
                return True
            else:
                logger.warning(f"K/V SET {key} failed: HTTP {resp.status}")
                return False
    except Exception:
        logger.exception(f"K/V SET {key} error")
        return False


async def kv_delete(key: str) -> bool:
    """
    Delete a key from the K/V store.

    Args:
        key: The key to delete

    Returns:
        True if successful (or key didn't exist), False on error.
    """
    try:
        session = await _get_kv_session()
        async with session.delete(f"{KV_BASE_URL}/{key}") as resp:
            if resp.status in (200, 404):
                logger.info(f"K/V DELETE {key}")
                return True
            else:
                logger.warning(f"K/V DELETE {key} failed: HTTP {resp.status}")
                return False
    except Exception:
        logger.exception(f"K/V DELETE {key} error")
        return False


async def check_intent_payment(intent_id: str, core_lane_url: str) -> dict:
    """
    Query lane state to check if payment was made for an intent using core-lane RPC.

    This demonstrates how containers can read lane state to verify payments.
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "method": "lane_getIntentState",
                "params": [intent_id],
                "id": 1,
            }
            async with session.post(
                f"{core_lane_url}/",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("result", {})
                else:
                    logger.warning(
                        f"Error checking intent payment: HTTP {response.status}"
                    )
                    return {}
    except asyncio.TimeoutError as e:
        logger.exception("Timeout while checking intent payment")
        return {}
    except aiohttp.ClientError as e:
        logger.exception("Network error while checking intent payment")
        return {}
    except json.JSONDecodeError as e:
        logger.exception("Failed to parse JSON response when checking intent payment")
        return {}
    except Exception as e:
        logger.exception("Unexpected error checking intent payment")
        return {}


async def check_transaction_state(tx_hash: str, core_lane_url: str) -> dict:
    """
    Query lane state to check transaction details (confirmations, amount, sender, etc.).

    This demonstrates how containers can read lane state to check transaction status.
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "method": "lane_getTransactionState",
                "params": [tx_hash],
                "id": 1,
            }
            async with session.post(
                f"{core_lane_url}/",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("result", {})
                else:
                    logger.warning(
                        f"Error checking transaction state: HTTP {response.status}"
                    )
                    return {}
    except asyncio.TimeoutError as e:
        logger.exception("Timeout while checking transaction state")
        return {}
    except aiohttp.ClientError as e:
        logger.exception("Network error while checking transaction state")
        return {}
    except json.JSONDecodeError as e:
        logger.exception(
            "Failed to parse JSON response when checking transaction state"
        )
        return {}
    except Exception as e:
        logger.exception("Unexpected error checking transaction state")
        return {}


app = web.Application()
app.router.add_get("/health", health)
app.router.add_post("/submit", submit_handler)


def run_app():
    """Function to run the app, used by watchgod/watchfiles"""
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_app()
