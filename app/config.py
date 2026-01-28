import os
from pathlib import Path

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/data/analytics.db"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ALLOWED_ORIGINS = [
    "https://lanelayer.github.io",
    "https://lanelayer.com",
    "https://www.lanelayer.com",
    "http://localhost:4000",
]
APP_VERSION = "1.0.0"
