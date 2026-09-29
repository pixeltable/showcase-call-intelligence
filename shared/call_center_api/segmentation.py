"""WhisperX segment labeling and transcript flattening (compare/PIPELINE_SPEC.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class LabeledSegment:
    speaker: str
    start_sec: float
    end_sec: float
    text: str


_AGENT_GREETING = re.compile(
    r"thank you for calling|how can i help|billing support|my name is",
    re.I,
)
_CUSTOMER_SPEECH = re.compile(
    r"i('m| am) calling|i want to cancel|i was charged|my subscription|refund|charged twice|price went up",
    re.I,
)


def _infer_speaker_from_text(text: str, idx: int) -> str:
    if _AGENT_GREETING.search(text):
        return "AGENT"
    if _CUSTOMER_SPEECH.search(text):
        return "CUSTOMER"
    return "AGENT" if idx == 0 else "CUSTOMER"


def _build_speaker_map(raw_segments: list[dict[str, Any]]) -> dict[str, str]:
    order: list[str] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        sp = str(seg.get("speaker", "UNKNOWN"))
        if sp not in order:
            order.append(sp)
    speaker_map: dict[str, str] = {}
    if order:
        speaker_map[order[0]] = "AGENT"
    if len(order) > 1:
        speaker_map[order[1]] = "CUSTOMER"
    return speaker_map


def _label_segment_speaker(raw_speaker: str, text: str, idx: int, speaker_map: dict[str, str]) -> str:
    if len(speaker_map) <= 1 and speaker_map:
        return _infer_speaker_from_text(text, idx)
    label = speaker_map.get(raw_speaker, raw_speaker)
    if label not in ("AGENT", "CUSTOMER"):
        return _infer_speaker_from_text(text, idx)
    return label


def extract_segments(diarized: dict[str, Any] | None) -> list[LabeledSegment]:
    """Extract WhisperX segments with AGENT/CUSTOMER labels."""
    if not diarized or not isinstance(diarized, dict):
        return []
    raw_segments = diarized.get("segments") or []
    speaker_map = _build_speaker_map(raw_segments)
    labeled: list[LabeledSegment] = []
    for idx, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        raw_speaker = str(seg.get("speaker", "UNKNOWN"))
        speaker = _label_segment_speaker(raw_speaker, text, idx, speaker_map)
        labeled.append(
            LabeledSegment(
                speaker=speaker,
                start_sec=float(seg.get("start", 0.0)),
                end_sec=float(seg.get("end", 0.0)),
                text=text,
            )
        )
    return labeled


def flatten_transcript(segments: list[LabeledSegment]) -> str:
    """Flat transcript text for LLM prompts with timestamps."""
    parts: list[str] = []
    for seg in segments:
        parts.append(f"[{seg.start_sec:.1f}s-{seg.end_sec:.1f}s] {seg.speaker}: {seg.text}")
    return "\n".join(parts)


def flatten_transcript_dicts(segments: list[dict[str, Any]] | None) -> str:
    """Flatten segment dicts (Pixeltable JSON array) to transcript text."""
    if not segments:
        return ""
    parts: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        speaker = str(seg.get("speaker", "UNKNOWN"))
        start = float(seg.get("start_sec", 0.0))
        end = float(seg.get("end_sec", 0.0))
        parts.append(f"[{start:.1f}s-{end:.1f}s] {speaker}: {text}")
    return "\n".join(parts)
