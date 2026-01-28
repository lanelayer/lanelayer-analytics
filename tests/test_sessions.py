from unittest.mock import AsyncMock, patch


def test_correlate_unknown_session(client):
    resp = client.post(
        "/api/v1/sessions/correlate",
        json={"session_id": "nonexistent", "cli_user_id": "cli_xyz"},
    )
    assert resp.status_code == 200
    assert resp.json()["correlated"] is False


@patch("app.routers.sessions.notify_session_correlated", new_callable=AsyncMock)
def test_correlate_existing_session(mock_slack, client):
    # First create a prompt to get a session
    client.post(
        "/api/v1/prompt/versions",
        json={"version": "3.0", "content": "test", "is_active": True},
    )
    resp = client.get("/api/v1/prompt/latest")
    session_id = resp.json()["session_id"]

    # Now track a web event to associate user with session
    client.post(
        "/api/v1/events",
        json={
            "event_type": "copy_prompt",
            "user_id": "web_abc",
            "session_id": session_id,
        },
    )

    # Correlate
    resp = client.post(
        "/api/v1/sessions/correlate",
        json={"session_id": session_id, "cli_user_id": "cli_def"},
    )
    assert resp.status_code == 200
    assert resp.json()["correlated"] is True
