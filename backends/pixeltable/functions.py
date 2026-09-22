"""UDFs for call center transcription and intelligence pipeline.

Transform semantics are defined in compare/PIPELINE_SPEC.md.
"""

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
from call_center_api.segmentation import extract_segments as shared_extract_segments
from call_center_api.segmentation import flatten_transcript_dicts
from call_center_api.verticals import DEFAULT_VERTICAL, get_profile


class SegmentRow(TypedDict):
    speaker: str
    start_sec: float
    end_sec: float
    text: str


@pxt.udf
def pick_source_audio(audio: pxt.Audio | None, extracted_audio: pxt.Audio | None) -> pxt.Audio | None:
    """Use uploaded audio when present, otherwise extracted video audio."""
    if audio is not None and str(audio).strip():
        return audio
    if extracted_audio is not None and str(extracted_audio).strip():
        return extracted_audio
    return None


@pxt.udf
def extract_segments(diarized: dict | None) -> list[SegmentRow]:
    """Extract WhisperX segments with AGENT/CUSTOMER labels."""
    labeled = shared_extract_segments(diarized)
    return [
        {
            "speaker": seg.speaker,
            "start_sec": seg.start_sec,
            "end_sec": seg.end_sec,
            "text": seg.text,
        }
        for seg in labeled
    ]


@pxt.udf
def flatten_transcript_segments(segments: list | None) -> str:
    """Flat transcript text for LLM prompts with timestamps."""
    return flatten_transcript_dicts(segments)


@pxt.udf
def handle_time_from_segments(segments: list | None) -> float:
    """Call duration from last segment end time."""
    if not segments:
        return 0.0
    ends = [float(seg.get("end_sec", 0.0)) for seg in segments if isinstance(seg, dict)]
    return max(ends) if ends else 0.0


@pxt.udf
def vertical_prompt(vertical: str | None, field: str) -> str:
    """Return vertical-specific LLM system prompt for an enrichment field."""
    prompts = get_profile(vertical or DEFAULT_VERTICAL).prompts
    value = getattr(prompts, field, None)
    if not isinstance(value, str):
        raise ValueError(f"Unknown prompt field: {field}")
    return value


@pxt.udf
def parse_summary_content(transcript: str | None, raw: str | None) -> str:
    if not (transcript or "").strip():
        return ""
    return format_summary(parse_summary(raw or ""))


@pxt.udf
def parse_action_items_content(transcript: str | None, raw: str | None) -> list[str]:
    if not (transcript or "").strip():
        return []
    return parse_action_items(raw or "")


@pxt.udf
def parse_sentiment_content(transcript: str | None, raw: str | None) -> dict:
    if not (transcript or "").strip():
        return dict(EMPTY_SENTIMENT)
    return parse_sentiment(raw or "")


@pxt.udf
def parse_category_content(transcript: str | None, raw: str | None) -> str:
    if not (transcript or "").strip():
        return "Uncategorized"
    return normalize_category(raw or "")


@pxt.udf
def parse_qa_content(transcript: str | None, raw: str | None) -> dict:
    if not (transcript or "").strip():
        return dict(EMPTY_QA)
    return parse_qa_scorecard(raw or "")


@pxt.udf
def is_flagged_sentiment(
    sentiment: dict | None, threshold: float = FLAGGED_SENTIMENT_THRESHOLD
) -> bool:
    if not isinstance(sentiment, dict):
        return False
    label = str(sentiment.get("label") or "").lower()
    score = sentiment.get("score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    if label == "negative":
        return True
    if score_f is not None and score_f < threshold:
        return True
    return has_negative_sentiment_moments(sentiment)


@pxt.udf
def derive_pipeline_status(
    diarized: dict | None,
    segments: list | None,
    summary: str | None,
    sentiment: dict | None,
    category: str | None,
    qa_scorecard: dict | None,
) -> str:
    """Derive pipeline status from column completion (no catalog access inside UDF)."""
    if diarized is None:
        return "queued"
    if segments is None:
        return "transcribing"
    if summary is None and sentiment is None:
        return "diarizing"
    if summary is None or sentiment is None:
        return "enriching"
    category_text = (category or "").strip()
    if not category_text:
        return "embedding"
    if not isinstance(qa_scorecard, dict) or not qa_scorecard:
        return "embedding"
    return "completed"


@pxt.udf
def has_video_source(media_type: str | None, video: pxt.Video | None) -> bool:
    return media_type == "video" and video is not None and str(video).strip() != ""


def _error_text(value: str | None) -> str:
    return str(value).strip() if value else ""


@pxt.udf
def display_status(
    pipeline_status: str | None,
    diarized_err: str | None,
    summary_err: str | None,
    sentiment_err: str | None,
    action_items_err: str | None,
    category_err: str | None,
    qa_err: str | None,
) -> str:
    """Read-time status. Stored pipeline_status stays a completion heuristic."""
    if any(
        _error_text(err)
        for err in (
            diarized_err,
            summary_err,
            sentiment_err,
            action_items_err,
            category_err,
            qa_err,
        )
    ):
        return "failed"
    return pipeline_status or "queued"
