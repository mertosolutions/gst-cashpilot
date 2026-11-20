import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import security


def test_firebase_verification_failure_never_accepts_unverified_claims(monkeypatch):
    from google.oauth2 import id_token

    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(auth_mode="firebase", firebase_project_id="project"))
    def reject(*args, **kwargs):
        raise ValueError("invalid signature")
    monkeypatch.setattr(id_token, "verify_firebase_token", reject)
    payload = base64.urlsafe_b64encode(json.dumps({"aud": "project", "sub": "victim"}).encode()).decode().rstrip("=")
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(authorization=f"Bearer header.{payload}.signature", x_demo_user=None)
    assert exc.value.status_code == 401


def test_live_reports_data_lookup_failure(client, monkeypatch):
    from app.controllers import live

    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(live, "get_current_user", fail)
    with client.websocket_connect("/api/v1/live") as ws:
        ws.send_json({"type": "auth", "user": "demo-owner"})
        assert ws.receive_json()["type"] == "status"
        assert ws.receive_json()["message"] == "Sign-in or data lookup failed. Check the API logs and try again."


def test_live_rejects_invalid_auth_message(client):
    with client.websocket_connect("/api/v1/live") as ws:
        ws.send_json({"type": "text", "text": "hello"})
        assert ws.receive_json()["message"] == "Voice sign-in was not received. Refresh the app and try again."
