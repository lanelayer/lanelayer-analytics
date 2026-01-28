import os
import tempfile
import pytest
from pathlib import Path

# Create a fresh temp DB for each test session
_tmp_path = Path(tempfile.mkdtemp()) / "test_analytics.db"
os.environ["DATABASE_PATH"] = str(_tmp_path)

# Patch before importing app modules
import app.config  # noqa: E402
import app.database  # noqa: E402

app.config.DATABASE_PATH = _tmp_path
app.database.DATABASE_PATH = _tmp_path


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
