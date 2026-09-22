"""Canonical Ollama enrichment response parsers (both backends).

System prompts live in call_center_api.verticals per vertical profile.
"""

from __future__ import annotations

import json
import re
from typing import Any

EMPTY_SENTIMENT: dict[str, Any] = {
    "label": "unknown",
    "score": 0.5,
    "rationale": "",
    "moments": [],
}

EMPTY_QA: dict[str, Any] = {
    "empathy": 0,
    "resolution": 0,
    "compliance": 0,
    "overall": 0,
    "notes": "",
}

_PREAMBLE_RE = re.compile(
    r"^(here are|below are|summary:|the following|call summary)",
    re.I,
)
_BULLET_PREFIX_RE = re.compile(r"^[\s•\-\*]+")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_VALID_LABELS = frozenset({"positive", "neutral", "negative"})


def extract_json(raw: str) -> str | None:
    """Return a JSON object/array substring from model output, or None."""
    text = (raw or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue
    return None


def _strip_markdown(text: str) -> str:
    cleaned = _MARKDOWN_BOLD_RE.sub(r"\1", text)
    cleaned = cleaned.replace("*", "")
    return cleaned.strip()


def _is_preamble(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(_PREAMBLE_RE.match(stripped))


def _parse_markdown_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _is_preamble(stripped):
            continue
        if _BULLET_PREFIX_RE.match(stripped):
            item = _BULLET_PREFIX_RE.sub("", stripped).strip()
            item = re.sub(r"^[^:]+:\s*", "", item, count=1) if ":" in item[:40] else item
            item = _strip_markdown(item)
            if item:
                bullets.append(item)
        elif bullets:
            bullets[-1] = f"{bullets[-1]} {stripped}"
    return bullets


def parse_summary(raw: str) -> list[str]:
    """Parse summary model output into clean bullet strings."""
    text = (raw or "").strip()
    if not text:
        return []

    json_text = extract_json(text)
    if json_text:
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("bullets", "summary", "points"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [_strip_markdown(str(item)) for item in value if str(item).strip()]
        if isinstance(parsed, list):
            return [_strip_markdown(str(item)) for item in parsed if str(item).strip()]

    bullets = _parse_markdown_bullets(text)
    if bullets:
        return bullets

    lines = [_strip_markdown(line.strip()) for line in text.splitlines() if line.strip() and not _is_preamble(line)]
    return [line for line in lines if line]


def format_summary(bullets: list[str]) -> str:
    """Join parsed bullets for API/DB storage."""
    return "\n".join(bullet for bullet in bullets if bullet)


def summary_lines(summary: str | None) -> list[str]:
    """Split stored summary into display lines."""
    if not summary:
        return []
    return [line.strip() for line in summary.splitlines() if line.strip()]


def parse_action_items(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []

    json_text = extract_json(text) or text
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        for key in ("actionItems", "action_items", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
    return []


def _clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(10.0, score))


def parse_qa_scorecard(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return dict(EMPTY_QA)

    json_text = extract_json(text) or text
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return dict(EMPTY_QA)

    if not isinstance(parsed, dict):
        return dict(EMPTY_QA)

    return {
        "empathy": _clamp_score(parsed.get("empathy")),
        "resolution": _clamp_score(parsed.get("resolution")),
        "compliance": _clamp_score(parsed.get("compliance")),
        "overall": _clamp_score(parsed.get("overall")),
        "notes": str(parsed.get("notes", "") or ""),
    }


def _normalize_moment(entry: dict[str, Any], *, default_polarity: str = "negative") -> dict[str, Any] | None:
    reason = str(entry.get("reason", "") or "").strip()
    if not reason:
        return None
    polarity = str(entry.get("polarity", default_polarity)).lower()
    if polarity not in _VALID_LABELS:
        polarity = default_polarity
    moment: dict[str, Any] = {"reason": reason, "polarity": polarity}
    start_sec = entry.get("start_sec")
    if start_sec is not None:
        try:
            moment["start_sec"] = float(start_sec)
        except (TypeError, ValueError):
            pass
    end_sec = entry.get("end_sec")
    if end_sec is not None:
        try:
            moment["end_sec"] = float(end_sec)
        except (TypeError, ValueError):
            pass
    return moment


def _normalize_moments(raw_moments: Any, *, default_polarity: str = "negative") -> list[dict[str, Any]]:
    if not isinstance(raw_moments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_moments:
        if not isinstance(item, dict):
            continue
        moment = _normalize_moment(item, default_polarity=default_polarity)
        if moment is not None:
            normalized.append(moment)
    return normalized


def sentiment_moments(sentiment: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized moments from stored sentiment, including legacy flags."""
    if not sentiment or not isinstance(sentiment, dict):
        return []
    moments = _normalize_moments(sentiment.get("moments"))
    if moments:
        return moments
    return _normalize_moments(sentiment.get("flags"), default_polarity="negative")


def has_negative_sentiment_moments(sentiment: dict[str, Any] | None) -> bool:
    return any(m.get("polarity") == "negative" for m in sentiment_moments(sentiment))


def parse_sentiment(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return dict(EMPTY_SENTIMENT)

    json_text = extract_json(text) or text
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return dict(EMPTY_SENTIMENT)

    if not isinstance(parsed, dict):
        return dict(EMPTY_SENTIMENT)

    label = str(parsed.get("label", "unknown")).lower()
    if label not in _VALID_LABELS:
        label = "unknown"

    try:
        score = float(parsed.get("score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))

    moments = _normalize_moments(parsed.get("moments"))
    if not moments:
        moments = _normalize_moments(parsed.get("flags"), default_polarity="negative")

    return {
        "label": label,
        "score": score,
        "rationale": str(parsed.get("rationale", "") or ""),
        "moments": moments,
    }


def normalize_category(raw: str) -> str:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return "Uncategorized"
    first_line = text.splitlines()[0].strip()
    return first_line or "Uncategorized"
