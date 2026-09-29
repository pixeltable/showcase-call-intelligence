"""Call intelligence on Pixeltable: schema, pipeline, and HTTP in one file.

Insert a call and Pixeltable extracts the audio from a video, transcribes and diarizes it with
WhisperX, labels the speakers, runs five Ollama enrichments, and embeds every segment for search.
Nothing below schedules that work, records its progress, or cleans up after it: the columns
declare what each row contains, and a failed cell keeps its error beside the others.

    pxt init
    pxt schema update app.py call_center
    pxt service update app.py call_center --port 8000
"""

import functools
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pixeltable as pxt
import pixeltable.functions as pxtf
from fastapi import File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pixeltable.functions.huggingface import sentence_transformer
from pixeltable.functions.json import list_iterator
from pixeltable.functions.ollama import chat
from pixeltable.functions.string import contains
from pixeltable.functions.uuid import uuid7
from pixeltable.functions.video import extract_audio
from pixeltable.functions.whisperx import transcribe
from pixeltable.serving import FastAPIRouter
from pydantic import BaseModel, Field

import config
import functions as f
from call_center_api.constants import ALLOWED_UPLOAD_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS
from call_center_api.verticals import normalize_vertical

TableModel = pxt.model_base()
EMBED = sentence_transformer.using(model_id=config.EMBED_MODEL, normalize_embeddings=True)


def ollama(messages, *, json: bool = True):
    """One Ollama call. Null messages (no speech) skip it."""
    return chat(messages=messages, model=config.OLLAMA_MODEL, format="json" if json else None)["message"]["content"]


# ---------------------------------------------------------------- the pipeline


class Calls(TableModel, name="calls"):
    id = pxt.Column(type=pxt.UUID, primary_key=True)
    audio: pxt.Audio | None
    video: pxt.Video | None
    media_type: pxt.String
    call_date: pxt.Timestamp
    agent_id: pxt.String
    customer_id: pxt.String
    queue: pxt.String
    vertical: pxt.String
    original_filename: pxt.String

    extracted_audio = extract_audio(video, format="mp3")
    source_audio = f.pick_source_audio(audio, extracted_audio)
    diarized = transcribe(
        source_audio,
        model=config.WHISPERX_MODEL,
        diarize=True,
        num_speakers=2,
        diarization_model_name=config.WHISPERX_DIARIZATION_MODEL,
    )
    segments = f.extract_segments(diarized)
    transcript = f.flatten_transcript(segments)
    handle_time_sec = f.handle_time(segments)

    summary = f.parse_summary_content(transcript, ollama(f.chat_messages(vertical, transcript, "summary")))
    action_items = f.parse_action_items_content(
        transcript, ollama(f.chat_messages(vertical, transcript, "action_items"))
    )
    sentiment = f.parse_sentiment_content(transcript, ollama(f.chat_messages(vertical, transcript, "sentiment")))
    category = f.parse_category_content(
        transcript, ollama(f.chat_messages(vertical, transcript, "category"), json=False)
    )
    qa_scorecard = f.parse_qa_content(transcript, ollama(f.chat_messages(vertical, transcript, "qa")))


class TranscriptSegments(
    TableModel,
    name="transcript_segments",
    base=Calls.where(Calls.segments != None),  # noqa: E711
    iterator=list_iterator(Calls.segments),
):
    __indexes__ = [pxt.EmbeddingIndex(text, embedding=EMBED, name="segments_embed")]  # type: ignore[name-defined]


class CoachingComments(TableModel, name="coaching_comments"):
    id = pxt.Column(value=uuid7(), primary_key=True)
    call_id: pxt.UUID
    segment_id: pxt.String | None
    start_sec: pxt.Float
    author: pxt.String
    comment: pxt.String
    created_at: pxt.Timestamp


# -------------------------------------------------------------------- queries


def errors(t=Calls):
    """Per-cell errors in pipeline order. A failed cell also fails every column computed from it."""
    return [t.extracted_audio.errormsg, t.diarized.errormsg, t.summary.errormsg, t.action_items.errormsg,
            t.sentiment.errormsg, t.category.errormsg, t.qa_scorecard.errormsg]  # fmt: skip


def no_errors(t=Calls):
    """SQL-expressible, so filters on it keep the index scan and the LIMIT in Postgres."""
    cond = t.extracted_audio.errormsg == None  # noqa: E711
    for err in errors(t)[1:]:
        cond &= err == None  # noqa: E711
    return cond


def summary_columns() -> dict:
    """CallSummary in shared/call_center_api/schemas.py, named as the contract names it."""
    return dict(
        id=Calls.id,
        call_date=Calls.call_date,
        agent_id=Calls.agent_id,
        customer_id=Calls.customer_id,
        queue=Calls.queue,
        vertical=Calls.vertical,
        duration_sec=Calls.handle_time_sec,
        handle_time_sec=Calls.handle_time_sec,
        status=f.call_status(errors()),
        category=Calls.category,
        summary=Calls.summary,
        sentiment_label=Calls.sentiment.label,
        sentiment_score=Calls.sentiment.score,
        media_type=Calls.media_type,
        has_video_source=Calls.video != None,  # noqa: E711
    )


@pxt.query
def list_calls(agent_id: str = "", queue: str = "", sentiment_label: str = "", min_handle_time: float = -1.0,
               limit: int = 50):  # fmt: skip
    return (
        Calls.where(
            ((agent_id == "") | (Calls.agent_id == agent_id))
            & ((queue == "") | (Calls.queue == queue))
            & ((sentiment_label == "") | (Calls.sentiment.label == sentiment_label))
            & ((min_handle_time < 0) | (Calls.handle_time_sec >= min_handle_time))
        )
        .order_by(Calls.call_date, asc=False)
        .limit(limit)
        .select(**summary_columns())
    )


@pxt.query
def flagged_calls(limit: int = 50):
    return (
        Calls.where(no_errors() & f.is_flagged(Calls.sentiment))
        .order_by(Calls.call_date, asc=False)
        .limit(limit)
        .select(**summary_columns())
    )


@functools.cache
def detail_query() -> pxt.Query:
    """CallDetail without comments. Built once per process and filtered per request, as declared routes
    are: building a query resolves the table once per selected expression."""
    return Calls.select(
        **summary_columns(),
        original_filename=Calls.original_filename,
        action_items=Calls.action_items,
        sentiment=Calls.sentiment,
        qa_scorecard=Calls.qa_scorecard,
        error_message=f.first_error(errors()),
        segments=f.segments_with_ids(Calls.id, Calls.segments),
    )


def hit_columns() -> dict:
    """SearchHit: the view inherits every call column, so no join."""
    s = TranscriptSegments
    return dict(
        call_id=s.id,
        segment_id=f.segment_id(s.id, s.pos),
        agent_id=s.agent_id,
        customer_id=s.customer_id,
        queue=s.queue,
        call_date=s.call_date,
        speaker=s.speaker,
        start_sec=s.start_sec,
        end_sec=s.end_sec,
        text=s.text,
        segment_pos=s.pos,
        media_type=s.media_type,
        original_filename=s.original_filename,
    )


@functools.cache
def keyword_hits_query() -> pxt.Query:
    return TranscriptSegments.select(**hit_columns())


@functools.cache
def comments_query() -> pxt.Query:
    c = CoachingComments
    return c.select(c.id, c.call_id, c.segment_id, c.start_sec, c.author, c.comment, c.created_at)


# ------------------------------------------------------------------------ API

api = FastAPIRouter(name="api", prefix="/api")

# Declared: the rows come straight from a @pxt.query, wrapped as {"rows": [...]}.
api.add_query_route(path="/calls", query=list_calls, method="get")
api.add_query_route(path="/calls/flagged", query=flagged_calls, method="get")

# Hand-written below. Paths with parameters (/calls/{id}) cannot be declared, and one upload field
# feeds either the audio or the video column, which add_insert_route cannot express.

# Inserts into one table serialize on its lock, so one worker is the real concurrency either way;
# the Reference runs one Celery worker process for the same reason.
_inserts = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pxt-insert")
_in_flight: dict[uuid.UUID, dict] = {}  # accepted, not yet committed: a row is invisible until computed
_failed: dict[uuid.UUID, str] = {}  # inserts that raised before any row was stored


def _insert(row: dict) -> None:
    try:
        # 'ignore' stores the row even when a cell fails; the error stays on that cell.
        Calls.insert([row], on_error="ignore")
    except Exception as exc:
        _failed[row["id"]] = f"{type(exc).__name__}: {exc}"
    finally:
        _in_flight.pop(row["id"], None)


@api.post("/calls/upload", status_code=202)
def upload_call(
    audio: UploadFile = File(...),
    call_date: datetime = Form(...),
    agent_id: str = Form(...),
    customer_id: str = Form(...),
    queue: str = Form(...),
    vertical: str = Form("call_center"),
):
    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    audio.file.seek(0, 2)
    if audio.file.tell() > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {config.MAX_UPLOAD_MB}MB limit")
    audio.file.seek(0)

    call_id = uuid.uuid4()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOAD_DIR / f"{call_id}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(audio.file, out)
    is_video = suffix in ALLOWED_VIDEO_EXTENSIONS
    row = {
        "id": call_id,
        "audio": None if is_video else str(dest),
        "video": str(dest) if is_video else None,
        "media_type": "video" if is_video else "audio",
        "call_date": call_date,
        "agent_id": agent_id,
        "customer_id": customer_id,
        "queue": queue,
        "vertical": normalize_vertical(vertical),
        "original_filename": Path(audio.filename or dest.name).name,
    }
    _in_flight[call_id] = row
    _inserts.submit(_insert, row)
    return {"id": str(call_id), "status": "queued"}


@api.get("/calls/kpis")
def get_kpis():
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    row = (
        Calls.where((Calls.call_date >= week_ago) & no_errors())
        .select(
            call_count=pxtf.count(Calls.id),
            avg_handle_time_sec=pxtf.mean(Calls.handle_time_sec),
            avg_sentiment_score=pxtf.mean(Calls.sentiment.score.astype(pxt.Float)),
        )
        .collect()[0]
    )
    return {k: v or 0 for k, v in row.items()}


@api.get("/calls/{call_id}")
def get_call(call_id: uuid.UUID):
    rows = detail_query().where(Calls.id == call_id).collect()
    if len(rows) == 1:
        return {**rows[0], "audio_path": f"/api/calls/{call_id}/audio", "comments": list_comments(call_id)}
    if call_id in _in_flight or call_id in _failed:
        return _unstored(call_id)
    raise HTTPException(status_code=404, detail="Call not found")


def _unstored(call_id: uuid.UUID) -> dict:
    """An accepted upload with no row yet. Pixeltable cannot say which stage it is in."""
    row = _in_flight.get(call_id) or {}
    error = _failed.get(call_id)
    return {
        **{k: row.get(k) for k in ("call_date", "agent_id", "customer_id", "queue", "vertical", "media_type")},
        "id": str(call_id),
        "status": "failed" if error else "processing",
        "error_message": error,
        "original_filename": row.get("original_filename", ""),
        "has_video_source": row.get("video") is not None,
        "segments": [],
        "comments": [],
    }


def _media_file(call_id: uuid.UUID, column) -> FileResponse:
    rows = Calls.where(Calls.id == call_id).select(path=column.localpath, name=Calls.original_filename).collect()
    path = Path(rows[0]["path"]).resolve() if len(rows) == 1 and rows[0]["path"] else None
    # whatever path a writer stored, serve only uploads and Pixeltable's own media
    if path is None or not path.is_file() or not any(path.is_relative_to(root) for root in config.MEDIA_ROOTS):
        raise HTTPException(status_code=404, detail="Media not available")
    return FileResponse(path, filename=Path(rows[0]["name"]).name)


@api.get("/calls/{call_id}/audio")
def get_call_audio(call_id: uuid.UUID):
    return _media_file(call_id, Calls.source_audio)


@api.get("/calls/{call_id}/video")
def get_call_video(call_id: uuid.UUID):
    return _media_file(call_id, Calls.video)


@api.delete("/calls/{call_id}", status_code=204)
def delete_call(call_id: uuid.UUID):
    rows = Calls.where(Calls.id == call_id).select(audio=Calls.audio.localpath, video=Calls.video.localpath).collect()
    if len(rows) == 0:
        raise HTTPException(status_code=404, detail="Call not found")
    CoachingComments.delete(where=CoachingComments.call_id == call_id)
    # The segments view and its embedding index follow the call row; the uploads are ours to remove.
    Calls.delete(where=Calls.id == call_id)
    for path in (rows[0]["audio"], rows[0]["video"]):
        if path and Path(path).is_relative_to(config.UPLOAD_DIR):
            Path(path).unlink(missing_ok=True)


@api.get("/search")
def search(
    q: str = Query(min_length=1, max_length=500),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(20, ge=1, le=100),
):
    text, s = q.strip(), TranscriptSegments
    hits: dict[str, dict] = {}
    if mode in ("keyword", "hybrid"):
        found = keyword_hits_query().where(contains(s.text, text, case=False) & no_errors(s))
        for row in found.order_by(s.call_date, asc=False).limit(limit).collect():
            hits.setdefault(row["segment_id"], {**row, "score": 1.0, "match_type": "keyword"})
    if mode in ("semantic", "hybrid") and len(hits) < limit:
        sim = s.text.similarity(string=text)
        for row in s.where(no_errors(s)).order_by(sim, asc=False).limit(limit).select(**hit_columns(), score=sim).collect():
            hits.setdefault(row["segment_id"], {**row, "match_type": "semantic"})
    return list(hits.values())[:limit]


class CommentCreate(BaseModel):
    call_id: uuid.UUID
    segment_id: str | None = None
    start_sec: float = 0.0
    author: str = Field(min_length=1, max_length=128)
    comment: str = Field(min_length=1)


@api.post("/comments", status_code=201)
def create_comment(payload: CommentCreate):
    rows = Calls.where(Calls.id == payload.call_id).select(segments=Calls.segments).collect()
    if len(rows) == 0:
        raise HTTPException(status_code=404, detail="Call not found")
    if payload.segment_id is not None:
        prefix, _, pos = payload.segment_id.rpartition(":")
        if prefix != str(payload.call_id) or not pos.isdigit() or int(pos) >= len(rows[0]["segments"] or []):
            raise HTTPException(status_code=400, detail="Invalid segment for call")
    row = {**payload.model_dump(), "created_at": datetime.now(timezone.utc)}
    stored = CoachingComments.insert([row], return_rows=True).rows[0]
    return {**row, "id": stored["id"]}


@api.get("/comments/call/{call_id}")
def list_comments(call_id: uuid.UUID) -> list[dict]:
    c = CoachingComments
    return list(comments_query().where(c.call_id == call_id).order_by(c.created_at).collect())


@api.get("/health")
def health():
    checks = {"catalog": _check(lambda: Calls.table and None), "ollama": _check(_ollama_ready),
              "embed_model": _check(lambda: config.EMBED_MODEL)}  # fmt: skip
    status = "ok" if all(c["ok"] for c in checks.values()) else "degraded"
    return {"status": status, "backend": "pixeltable", "checks": checks}


def _check(fn) -> dict:
    try:
        return {"ok": True, "detail": fn()}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _ollama_ready() -> str:
    names = [m["name"] for m in httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5).json()["models"]]
    if not any(n.split(":")[0] == config.OLLAMA_MODEL.split(":")[0] for n in names):
        raise RuntimeError(f"Missing model {config.OLLAMA_MODEL}")
    return f"Models available at {config.OLLAMA_HOST}"
