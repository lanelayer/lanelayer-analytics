from unittest.mock import AsyncMock, patch


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@patch("app.routers.events.notify_prompt_copied", new_callable=AsyncMock)
def test_track_web_event(mock_slack, client):
    resp = client.post(
        "/api/v1/events",
        json={
            "event_type": "copy_prompt",
            "user_id": "web_test123",
            "session_id": "sess_abc",
            "data": {"prompt_version": "2.1"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["event_id"] > 0
    mock_slack.assert_called_once()


@patch("app.routers.events.notify_cli_first_run", new_callable=AsyncMock)
def test_track_cli_event(mock_slack, client):
    resp = client.post(
        "/api/v1/events/cli",
        json={
            "user_id": "cli_test456",
            "command": "up",
            "profile": "dev",
            "success": True,
            "cli_version": "0.4.9",
            "os": "darwin",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    mock_slack.assert_called_once()


def test_track_event_missing_fields(client):
    resp = client.post("/api/v1/events", json={"event_type": "test"})
    assert resp.status_code == 422  # Validation error - user_id required
