"""Reference request and failure behavior without a live database, broker, or model call."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import calls, search


@pytest.fixture
def api():
    application = FastAPI()
    application.include_router(calls.router)
    application.include_router(search.router)
    db = Mock()
    application.dependency_overrides[get_db] = lambda: db
    with TestClient(application) as client:
        yield client, db


@pytest.mark.parametrize("path", ["/api/calls?limit=-1", "/api/calls/flagged?limit=201", "/api/search?q=x&limit=0",
                                  "/api/search?q=%20"])
def test_invalid_queries_do_not_touch_the_store(api, path: str) -> None:
    client, db = api
    assert client.get(path).status_code == 422
    db.query.assert_not_called()


def test_semantic_provider_failure_is_not_an_empty_success(api, monkeypatch) -> None:
    client, _ = api
    def fail(text: str):
        raise RuntimeError("Fixture embedding failure")
    monkeypatch.setattr(search, "embed_text", fail)
    response = client.get("/api/search", params={"q": "billing", "mode": "semantic"})
    assert response.status_code == 503
    assert "keyword" in response.json()["detail"]


def test_flagged_filter_reaches_matches_beyond_an_unrelated_page(api) -> None:
    client, db = api
    neutral = SimpleNamespace(sentiment={"label": "neutral", "score": 0.5})
    flagged = SimpleNamespace(id=uuid.uuid4(), sentiment={"label": "negative", "score": 0.2}, media_type="audio",
                              call_date=datetime.now(timezone.utc), agent_id="a", customer_id="c", queue="q",
                              vertical="call_center", duration_sec=1.0, handle_time_sec=1.0, status="completed",
                              category="Billing", summary="Review charge", video_path=None)
    db.query.return_value.filter.return_value.order_by.return_value.yield_per.return_value = iter([neutral] * 201 + [flagged])
    response = client.get("/api/calls/flagged", params={"limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == str(flagged.id)


def test_extracted_audio_uses_its_actual_extension(api, tmp_path, monkeypatch) -> None:
    client, db = api
    path = tmp_path / "extracted.mp3"
    path.write_bytes(b"fixture audio")
    db.get.return_value = SimpleNamespace(audio_path=str(path), original_filename="original-video.mp4")
    monkeypatch.setattr(calls, "resolve_upload_file", lambda value: path)
    response = client.get(f"/api/calls/{uuid.uuid4()}/audio")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")
    assert "original-video.mp3" in response.headers["content-disposition"]
