"""Class-based Pixeltable schema for the call-center intelligence pipeline.

python schema.py
RESET_SCHEMA=true python schema.py
"""

from __future__ import annotations

import os
import shutil
import signal
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HOME = _REPO_ROOT / "data" / "pixeltable"
os.environ.setdefault("PIXELTABLE_HOME", str(_DEFAULT_HOME))


def _stop_embedded_postgres(pgdata: Path) -> None:
    """Stop Pixeltable's embedded Postgres before deleting pgdata."""
    pid_file = pgdata / "postmaster.pid"
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text().splitlines()[0].strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def maybe_reset_catalog() -> None:
    """Wipe local catalog when RESET_SCHEMA=true.

    Required when the embedding index function changes (destructive). Must run
    before Pixeltable opens the catalog.
    """
    if os.getenv("RESET_SCHEMA", "false").lower() != "true":
        return
    home = Path(os.environ.get("PIXELTABLE_HOME", str(_DEFAULT_HOME)))
    pgdata = home / "pgdata"
    if pgdata.is_dir():
        _stop_embedded_postgres(pgdata)
        shutil.rmtree(pgdata, ignore_errors=True)
    for name in ("media", "uploads", "file_cache", "logs"):
        path = home / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


maybe_reset_catalog()

import config
import functions
import pixeltable as pxt
from pixeltable.functions.huggingface import sentence_transformer
from pixeltable.functions.json import list_iterator
from pixeltable.functions.ollama import chat
from pixeltable.functions.uuid import uuid7
from pixeltable.functions.video import extract_audio
from pixeltable.functions.whisperx import transcribe

TableModel = pxt.model_base()
embed_fn = sentence_transformer.using(
    model_id=config.EMBED_MODEL,
    normalize_embeddings=True,
)


class Calls(TableModel, name="calls"):
    uuid = pxt.Column(type=pxt.UUID, primary_key=True)
    audio: pxt.Audio | None
    video: pxt.Video | None
    media_type: pxt.String | None
    call_date: pxt.Timestamp | None
    agent_id: pxt.String | None
    customer_id: pxt.String | None
    queue: pxt.String | None
    vertical: pxt.String | None
    duration_sec: pxt.Float | None
    original_filename: pxt.String | None

    extracted_audio = pxt.Column(value=extract_audio(video, format="mp3"))
    source_audio = functions.pick_source_audio(audio, extracted_audio)
    diarized = pxt.Column(
        value=transcribe(
            audio=source_audio,
            model=config.WHISPERX_MODEL,
            diarize=True,
            num_speakers=2,
            diarization_model_name=config.WHISPERX_DIARIZATION_MODEL,
        )
    )
    segments = functions.extract_segments(diarized)
    transcript_text = functions.flatten_transcript_segments(segments)
    handle_time_sec = functions.handle_time_from_segments(segments)

    summary_raw = chat(
        model=config.OLLAMA_MODEL,
        format="json",
        messages=[
            {"role": "system", "content": functions.vertical_prompt(vertical, "summary")},
            {"role": "user", "content": transcript_text},
        ],
    )["message"]["content"]
    summary = functions.parse_summary_content(transcript_text, summary_raw)

    action_items_raw = chat(
        model=config.OLLAMA_MODEL,
        format="json",
        messages=[
            {"role": "system", "content": functions.vertical_prompt(vertical, "action_items")},
            {"role": "user", "content": transcript_text},
        ],
    )["message"]["content"]
    action_items = functions.parse_action_items_content(transcript_text, action_items_raw)

    sentiment_raw = chat(
        model=config.OLLAMA_MODEL,
        format="json",
        messages=[
            {"role": "system", "content": functions.vertical_prompt(vertical, "sentiment")},
            {"role": "user", "content": transcript_text},
        ],
    )["message"]["content"]
    sentiment = functions.parse_sentiment_content(transcript_text, sentiment_raw)

    category_raw = chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": functions.vertical_prompt(vertical, "category")},
            {"role": "user", "content": transcript_text},
        ],
    )["message"]["content"]
    category = functions.parse_category_content(transcript_text, category_raw)

    qa_raw = chat(
        model=config.OLLAMA_MODEL,
        format="json",
        messages=[
            {"role": "system", "content": functions.vertical_prompt(vertical, "qa")},
            {"role": "user", "content": transcript_text},
        ],
    )["message"]["content"]
    qa_scorecard = functions.parse_qa_content(transcript_text, qa_raw)

    pipeline_status = functions.derive_pipeline_status(
        diarized,
        segments,
        summary,
        sentiment,
        category,
        qa_scorecard,
    )


class TranscriptSegments(
    TableModel,
    name="transcript_segments",
    base=Calls.where(Calls.segments != None),  # noqa: E711
    iterator=list_iterator(Calls.segments),
):
    __indexes__ = [pxt.EmbeddingIndex(text, embedding=embed_fn, name="segments_embed")]


class CoachingComments(TableModel, name="coaching_comments"):
    uuid = pxt.Column(value=uuid7(), primary_key=True)
    call_uuid: pxt.UUID
    segment_pos: pxt.Int
    start_sec: pxt.Float
    author: pxt.String
    comment: pxt.String
    timestamp: pxt.Timestamp


def apply() -> None:
    pxt.create_dir(config.APP_NAMESPACE, if_exists="ignore")
    TableModel.create_all(config.APP_NAMESPACE)


apply()

if __name__ == "__main__":
    print("Call center schema setup complete.")
