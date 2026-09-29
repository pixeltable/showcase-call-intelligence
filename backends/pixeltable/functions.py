"""UDFs the schema in app.py calls. Transform semantics: compare/PIPELINE_SPEC.md."""

from typing import TypedDict

import pixeltable as pxt

from call_center_api.constants import FLAGGED_SENTIMENT_THRESHOLD
from call_center_api.enrichment import (
    EMPTY_QA,
    EMPTY_SENTIMENT,
    format_summary,
    has_negative_sentiment_moments,
    normalize_category,
    parse_action_items,
    parse_qa_scorecard,
    parse_sentiment,
    parse_summary,
)
from call_center_api.segmentation import extract_segments as label_segments
from call_center_api.segmentation import flatten_transcript_dicts
from call_center_api.verticals import get_profile


class SegmentRow(TypedDict):
    speaker: str
    start_sec: float
    end_sec: float
    text: str


@pxt.udf
def pick_source_audio(audio: pxt.Audio | None, extracted_audio: pxt.Audio | None) -> pxt.Audio | None:
    """The uploaded audio, or the audio extracted from an uploaded video."""
    return audio if audio is not None else extracted_audio


@pxt.udf
def extract_segments(diarized: dict | None) -> list[SegmentRow]:
    """WhisperX segments labeled AGENT/CUSTOMER."""
    return [
        {"speaker": s.speaker, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in label_segments(diarized)
    ]


@pxt.udf
def flatten_transcript(segments: list | None) -> str | None:
    """Timestamped transcript for the LLM prompts; None when nothing was said, which skips the LLM calls."""
    return flatten_transcript_dicts(segments) or None


@pxt.udf
def handle_time(segments: list | None) -> float:
    ends = [float(s.get("end_sec", 0.0)) for s in segments or [] if isinstance(s, dict)]
    return max(ends, default=0.0)


@pxt.udf
def chat_messages(vertical: str, transcript: str, field: str) -> list[dict]:
    """System prompt for this vertical and field, then the transcript. A None transcript skips the call."""
    return [
        {"role": "system", "content": getattr(get_profile(vertical).prompts, field)},
        {"role": "user", "content": transcript},
    ]


@pxt.udf
def parse_summary_content(transcript: str | None, raw: str | None) -> str:
    return format_summary(parse_summary(raw or "")) if transcript else ""


@pxt.udf
def parse_action_items_content(transcript: str | None, raw: str | None) -> list[str]:
    return parse_action_items(raw or "") if transcript else []


@pxt.udf
def parse_sentiment_content(transcript: str | None, raw: str | None) -> dict:
    return parse_sentiment(raw or "") if transcript else dict(EMPTY_SENTIMENT)


@pxt.udf
def parse_category_content(transcript: str | None, raw: str | None) -> str:
    return normalize_category(raw or "") if transcript else "Uncategorized"


@pxt.udf
def parse_qa_content(transcript: str | None, raw: str | None) -> dict:
    return parse_qa_scorecard(raw or "") if transcript else dict(EMPTY_QA)


@pxt.udf
def is_flagged(sentiment: dict | None, threshold: float = FLAGGED_SENTIMENT_THRESHOLD) -> bool:
    if not isinstance(sentiment, dict):
        return False
    if str(sentiment.get("label") or "").lower() == "negative":
        return True
    try:
        if float(sentiment.get("score")) < threshold:
            return True
    except (TypeError, ValueError):
        pass
    return has_negative_sentiment_moments(sentiment)


@pxt.udf
def first_error(errors: list) -> str | None:
    """The first per-cell error message, in pipeline order."""
    return next((str(e).strip() for e in errors if e and str(e).strip()), None)


@pxt.udf
def call_status(errors: list) -> str:
    """A stored row is finished: every column is computed or holds its error."""
    return "failed" if any(e and str(e).strip() for e in errors) else "completed"


@pxt.udf
def segments_with_ids(call_id: pxt.UUID, segments: list | None) -> list[dict]:
    return [{"id": f"{call_id}:{pos}", "pos": pos, **seg} for pos, seg in enumerate(segments or [])]


@pxt.udf
def segment_id(call_id: pxt.UUID, pos: int) -> str:
    return f"{call_id}:{pos}"
