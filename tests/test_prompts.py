def test_no_active_prompt(client):
    resp = client.get("/api/v1/prompt/latest")
    assert resp.status_code == 404


def test_create_and_get_prompt(client):
    # Create a prompt version
    resp = client.post(
        "/api/v1/prompt/versions",
        json={
            "version": "2.1",
            "content": "# Build My Lane\nThis is the test prompt.",
            "is_active": True,
        },
    )
    assert resp.status_code == 200

    # Get latest
    resp = client.get("/api/v1/prompt/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "2.1"
    assert "session_id" in body
    assert "Session:" in body["content"]


def test_list_versions(client):
    resp = client.get("/api/v1/prompt/versions")
    assert resp.status_code == 200
    assert len(resp.json()["versions"]) >= 1
