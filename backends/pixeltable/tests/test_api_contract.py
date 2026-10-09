"""Exercise the real TableModel, media, view, index, and API with deterministic provider substitutes.

No tokens, model weights, Docker, paid calls, or existing catalog are needed. The temporary catalog
is created before Pixeltable is imported. Only the external model functions are substituted.

    uv run --with pytest python -m pytest tests/test_api_contract.py -q
"""

import json
import os
import sys
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import av
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_test_home = TemporaryDirectory(prefix="call-showcase-contract-")
os.environ["PIXELTABLE_HOME"] = _test_home.name
os.environ["PXT_UPLOAD_DIR"] = str(Path(_test_home.name) / "uploads")

import pixeltable as pxt  # noqa: E402

from call_center_api.schemas import CallDetail, CallSummary, CommentOut, SearchHit  # noqa: E402

_malformed_output = False
_chat_calls = 0
_embedding_failure = False
_asr_calls = 0
_embedding_calls = 0


@pxt.udf
def fixture_transcribe(audio: pxt.Audio, *, model: str, diarize: bool, num_speakers: int,
                       diarization_model_name: str) -> dict:
    global _asr_calls
    _asr_calls += 1
    with av.open(audio) as container:
        spoken = any(np.any(frame.to_ndarray()) for frame in container.decode(audio=0))
    return {"segments": [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 0.5, "text": "Thank you for calling billing support."},
        {"speaker": "SPEAKER_01", "start": 0.5, "end": 1.0, "text": "My subscription was charged twice."},
    ] if spoken else []}


@pxt.udf
def fixture_chat(messages: list[dict], *, model: str, format: str | None = None) -> dict:
    global _chat_calls
    _chat_calls += 1
    if _malformed_output:
        return {"message": {"content": ""}}
    prompt = messages[0]["content"].lower()
    if "summarize" in prompt:
        result = {"bullets": ["Customer disputes duplicate subscription billing."]}
    elif "extract action items" in prompt:
        result = ["Review the duplicate charge."]
    elif "sentiment" in prompt:
        result = {"label": "negative", "score": 0.2, "rationale": "Duplicate charge", "moments": []}
    elif "score this call" in prompt:
        result = {"empathy": 8, "resolution": 7, "compliance": 9, "overall": 8, "notes": "Review"}
    else:
        return {"message": {"content": "Billing Dispute"}}
    return {"message": {"content": json.dumps(result)}}


@pxt.udf
def fixture_embedding(text: str, *, model_id: str, normalize_embeddings: bool) -> pxt.Array[(768,), pxt.Float]:
    global _embedding_calls
    _embedding_calls += 1
    if _embedding_failure:
        raise RuntimeError("Fixture embedding provider is unavailable")
    vector = np.zeros(768, dtype=np.float32)
    vector[0] = 1.0
    return vector


@pytest.fixture(scope="module")
def api():
    with patch("pixeltable.functions.whisperx.transcribe", fixture_transcribe), \
         patch("pixeltable.functions.ollama.chat", fixture_chat), \
         patch("pixeltable.functions.huggingface.sentence_transformer", fixture_embedding):
        import app

    pxt.create_dir("contract_test", if_exists="ignore")
    app.TableModel.create_all("contract_test")
    app.api.bind("contract_test")
    application = FastAPI()
    application.include_router(app.api)
    with TestClient(application) as client:
        yield client, app
    app._inserts.shutdown(wait=True)
    pxt.drop_dir("contract_test", force=True)


def audio_file(name: str, *, spoken: bool) -> Path:
    path = Path(_test_home.name) / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes((b"\x01\x00" if spoken else b"\x00\x00") * 16000)
    return path


def upload(client: TestClient, path: Path, **metadata) -> str:
    with path.open("rb") as handle:
        response = client.post("/api/calls/upload", files={"audio": (path.name, handle, "audio/wav")}, data={
            "call_date": datetime.now(timezone.utc).isoformat(), "agent_id": "agent", "customer_id": "customer",
            "queue": "billing", **metadata,
        })
    assert response.status_code == 202, response.text
    return response.json()["id"]


def completed(client: TestClient, call_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/calls/{call_id}")
        assert response.status_code == 200, response.text
        call = response.json()
        CallDetail.model_validate(call)
        if call["status"] in ("completed", "failed"):
            return call
        time.sleep(0.05)
    pytest.fail("Fixture insert did not finish")


def test_empty_catalog_kpis_have_a_valid_response(api) -> None:
    client, _ = api
    response = client.get("/api/calls/kpis")
    assert response.status_code == 200, response.text
    assert response.json() == {"call_count": 0, "avg_handle_time_sec": 0.0, "avg_sentiment_score": 0.0}


def test_upload_pipeline_search_comments_and_delete(api) -> None:
    client, app = api
    before_chat = _chat_calls
    call_id = upload(client, audio_file("spoken.wav", spoken=True))
    call = completed(client, call_id)
    assert call["status"] == "completed", call["error_message"]
    assert call["enrichment_profile"] == "full"
    assert _chat_calls - before_chat == 5
    assert len(call["segments"]) == 2
    assert all(uuid.UUID(segment["id"]) for segment in call["segments"])
    roster = client.get("/api/calls", params={"limit": 1, "sentiment_label": "negative"}).json()["rows"]
    assert roster[0]["id"] == call_id
    CallSummary.model_validate(roster[0])
    assert client.get("/api/calls/kpis").json()["call_count"] == 1
    assert client.get(f"/api/calls/{call_id}/audio").status_code == 200
    for mode in ("keyword", "semantic", "hybrid"):
        hits = client.get("/api/search", params={"q": "billing", "mode": mode}).json()
        assert hits
        for hit in hits:
            SearchHit.model_validate(hit)
    segment = call["segments"][0]
    comment = client.post("/api/comments", json={"call_id": call_id, "segment_id": segment["id"],
                          "start_sec": segment["start_sec"], "author": "reviewer", "comment": "Investigate"})
    assert comment.status_code == 201, comment.text
    CommentOut.model_validate(comment.json())
    assert client.get(f"/api/calls/{call_id}").json()["comments"][0]["segment_id"] == segment["id"]
    assert client.delete(f"/api/calls/{call_id}").status_code == 204
    assert client.get(f"/api/calls/{call_id}").status_code == 404
    assert app.TranscriptSegments.where(app.TranscriptSegments.id == uuid.UUID(call_id)).count() == 0
    assert app.CoachingComments.where(app.CoachingComments.call_id == uuid.UUID(call_id)).count() == 0
    assert not list(app.config.UPLOAD_DIR.glob(f"{call_id}.*"))


@pytest.mark.skipif(os.getenv("PXT_ENRICHMENT_PROFILE") != "core", reason="run separately with the core schema")
def test_core_profile_skips_optional_model_calls_and_exposes_omission(api, monkeypatch) -> None:
    client, app = api
    monkeypatch.setattr(app, "_ollama_ready", lambda: None)
    assert client.get("/api/health").json()["enrichment_profile"] == "core"
    assert client.get("/api/calls/kpis").json()["avg_sentiment_score"] is None
    before = _chat_calls
    call_id = upload(client, audio_file("core.wav", spoken=True))
    call = completed(client, call_id)
    assert call["status"] == "completed", call["error_message"]
    assert call["enrichment_profile"] == "core"
    assert _chat_calls - before == 1
    assert call["summary"] and call["segments"]
    for field in ("action_items", "sentiment", "qa_scorecard", "category"):
        assert call[field] is None
    roster = client.get("/api/calls").json()["rows"]
    assert roster[0]["enrichment_profile"] == "core"
    assert roster[0]["sentiment_score"] is None
    assert client.get("/api/calls/flagged").json()["rows"] == []
    assert client.get("/api/search", params={"q": "billing", "mode": "semantic"}).json()
    client.delete(f"/api/calls/{call_id}")
    before = _chat_calls
    silent_id = upload(client, audio_file("core-silence.wav", spoken=False))
    silent = completed(client, silent_id)
    assert silent["summary"] == "" and silent["segments"] == []
    assert silent["sentiment"] is None
    assert _chat_calls == before
    client.delete(f"/api/calls/{silent_id}")


def test_extension_recomputes_only_its_field_and_preserves_evidence(api):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "examples"))
    from extend_call import FIELD, exercise
    client, app = api
    call_id = upload(client, audio_file("extension.wav", spoken=True))
    completed(client, call_id)
    before_calls = (_chat_calls, _asr_calls, _embedding_calls)
    call_uuid = uuid.UUID(call_id)
    calls, comments = app.Calls.table, app.CoachingComments.table
    result = exercise(calls, comments, call_uuid)
    assert result["after_recompute"] is True
    assert result["transcript_summary_segments_unchanged"] is True
    assert result["comment_still_anchored"] is True
    assert before_calls == (_chat_calls, _asr_calls, _embedding_calls)
    assert FIELD not in calls.columns()
    assert comments.where(comments.call_id == call_uuid).count() == 0
    client.delete(f"/api/calls/{call_id}")


def test_silence_skips_model_calls(api) -> None:
    global _chat_calls
    client, _ = api
    before = _chat_calls
    call_id = upload(client, audio_file("silence.wav", spoken=False))
    call = completed(client, call_id)
    assert call["status"] == "completed"
    assert call["segments"] == []
    assert call["summary"] == ""
    assert call["sentiment"]["label"] == "unknown"
    assert _chat_calls == before
    client.delete(f"/api/calls/{call_id}")


def test_video_extraction_and_media_response_types(api) -> None:
    client, _ = api
    path = Path(_test_home.name) / "video.mp4"
    with av.open(str(path), mode="w") as container:
        video = container.add_stream("mpeg4", rate=12)
        video.width, video.height, video.pix_fmt = 128, 96, "yuv420p"
        audio = container.add_stream("aac", rate=16000)
        audio.layout = "mono"
        for index in range(12):
            frame = av.VideoFrame.from_ndarray(np.zeros((96, 128, 3), dtype=np.uint8), format="rgb24")
            frame.pts = index
            container.mux(video.encode(frame))
        container.mux(video.encode(None))
        samples = (np.sin(np.arange(16000) * (440 * 2 * np.pi / 16000)) * 10000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = 16000
        frame.pts = 0
        container.mux(audio.encode(frame))
        container.mux(audio.encode(None))
    call_id = upload(client, path)
    call = completed(client, call_id)
    assert call["status"] == "completed", call["error_message"]
    assert call["media_type"] == "video"
    assert call["has_video_source"]
    extracted = client.get(f"/api/calls/{call_id}/audio")
    assert extracted.status_code == 200
    assert extracted.headers["content-type"].startswith("audio/")
    assert ".mp3" in extracted.headers["content-disposition"]
    original = client.get(f"/api/calls/{call_id}/video")
    assert original.status_code == 200
    assert original.headers["content-type"] == "video/mp4"
    client.delete(f"/api/calls/{call_id}")


def test_malformed_model_output_is_recorded_as_failure(api) -> None:
    global _malformed_output
    client, _ = api
    _malformed_output = True
    try:
        call_id = upload(client, audio_file("invalid-model-output.wav", spoken=True))
        call = completed(client, call_id)
        assert call["status"] == "failed"
        assert "empty" in call["error_message"].lower()
        assert len(call["segments"]) == 2
        assert not client.get("/api/search", params={"q": "billing", "mode": "keyword"}).json()
    finally:
        _malformed_output = False
    client.delete(f"/api/calls/{call_id}")


@pytest.mark.parametrize("route", ["/api/calls", "/api/calls/flagged", "/api/search?q=billing"])
@pytest.mark.parametrize("limit", [0, -1, 201])
def test_invalid_query_limits_are_rejected(api, route, limit) -> None:
    client, _ = api
    assert client.get(route, params={"limit": limit}).status_code == 422


def test_blank_search_and_invalid_comment_are_rejected(api) -> None:
    client, _ = api
    assert client.get("/api/search", params={"q": " "}).status_code == 422
    assert client.post("/api/comments", json={"call_id": str(uuid.uuid4()), "author": "a", "comment": "x",
                                           "start_sec": -1}).status_code == 422


def test_index_failure_keeps_transform_data_and_surfaces_search_errors(api) -> None:
    """The status contract covers call transforms; index errors remain in SDK diagnostics and service logs."""
    global _embedding_failure
    client, app = api
    _embedding_failure = True
    call_id = upload(client, audio_file("embedding-failure.wav", spoken=True))
    try:
        call = completed(client, call_id)
        assert call["status"] == "completed"
        assert len(call["segments"]) == 2
        assert client.get("/api/search", params={"q": "billing", "mode": "keyword"}).json()
        assert client.get("/api/search", params={"q": "billing", "mode": "semantic"}).status_code == 503
        nodes = pxt.get_dir_tree("contract_test")
        assert any(node.get("error_count", 0) > 0 for node in nodes)
    finally:
        _embedding_failure = False
    # Failed vectors must not appear as unscored semantic hits when query embedding works again.
    assert client.get("/api/search", params={"q": "billing", "mode": "semantic"}).json() == []
    client.delete(f"/api/calls/{call_id}")
