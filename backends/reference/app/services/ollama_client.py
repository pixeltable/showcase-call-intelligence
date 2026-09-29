from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from call_center_api.enrichment import (
    EMPTY_QA,
    EMPTY_SENTIMENT,
    format_summary,
    normalize_category,
    parse_action_items,
    parse_qa_scorecard,
    parse_sentiment,
    parse_summary,
)
from call_center_api.verticals import get_profile


@dataclass
class LlmResult:
    summary: str
    action_items: list[str]
    sentiment: dict[str, Any]
    category: str
    qa_scorecard: dict[str, Any]


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_host.rstrip("/")
        self.model = settings.ollama_model

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        timeout = settings.ollama_timeout_sec
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return str((data.get("message") or {}).get("content", ""))
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Ollama request timed out after {timeout:.0f}s ({exc.__class__.__name__})"
            ) from exc

    def enrich_call(self, transcript: str, vertical: str = "call_center") -> LlmResult:
        prompts = get_profile(vertical).prompts
        if not transcript.strip():
            return LlmResult(
                summary="",
                action_items=[],
                sentiment=dict(EMPTY_SENTIMENT),
                category="Uncategorized",
                qa_scorecard=dict(EMPTY_QA),
            )

        summary_raw = self.chat(prompts.summary, transcript, json_mode=True)
        summary = format_summary(parse_summary(summary_raw))

        action_items = parse_action_items(self.chat(prompts.action_items, transcript, json_mode=True))
        sentiment = parse_sentiment(self.chat(prompts.sentiment, transcript, json_mode=True))
        category = normalize_category(self.chat(prompts.category, transcript))
        qa_scorecard = parse_qa_scorecard(self.chat(prompts.qa, transcript, json_mode=True))

        return LlmResult(
            summary=summary,
            action_items=action_items,
            sentiment=sentiment,
            category=category,
            qa_scorecard=qa_scorecard,
        )
