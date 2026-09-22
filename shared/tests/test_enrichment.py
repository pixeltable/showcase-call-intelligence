"""Tests for shared enrichment parsers."""

from call_center_api.enrichment import (
    format_summary,
    has_negative_sentiment_moments,
    normalize_category,
    parse_action_items,
    parse_qa_scorecard,
    parse_sentiment,
    parse_summary,
    sentiment_moments,
    summary_lines,
)


def test_parse_summary_json_bullets() -> None:
    raw = '{"bullets": ["Customer wanted to cancel.", "Agent processed cancellation."]}'
    bullets = parse_summary(raw)
    assert bullets == ["Customer wanted to cancel.", "Agent processed cancellation."]
    assert format_summary(bullets) == "Customer wanted to cancel.\nAgent processed cancellation."


def test_parse_summary_strips_preamble_and_markdown() -> None:
    raw = (
        "Here are 3-5 bullet points summarizing the call:\n"
        "* **Customer Issue:** High monthly fees.\n"
        "* **Agent's Actions:** Offered discount.\n"
    )
    bullets = parse_summary(raw)
    assert len(bullets) == 2
    assert "High monthly fees" in bullets[0]
    assert "Offered discount" in bullets[1]


def test_parse_action_items_array_and_wrapper() -> None:
    assert parse_action_items('["Send confirmation email"]') == ["Send confirmation email"]
    assert parse_action_items('{"action_items": ["Call back customer"]}') == ["Call back customer"]


def test_parse_qa_scorecard_clamps_scores() -> None:
    qa = parse_qa_scorecard('{"empathy": 12, "resolution": -1, "compliance": 7, "overall": 8, "notes": "ok"}')
    assert qa["empathy"] == 10.0
    assert qa["resolution"] == 0.0
    assert qa["notes"] == "ok"


def test_parse_sentiment_validates_label() -> None:
    sent = parse_sentiment('{"label": "NEGATIVE", "score": 1.5, "rationale": "upset", "moments": []}')
    assert sent["label"] == "negative"
    assert sent["score"] == 1.0


def test_parse_sentiment_moments_with_polarity() -> None:
    raw = (
        '{"label": "neutral", "score": 0.6, "rationale": "mixed", "moments": ['
        '{"start_sec": 12.5, "end_sec": 18.0, "polarity": "negative", "reason": "upset"}, '
        '{"start_sec": 45.0, "polarity": "positive", "reason": "refund offered"}'
        "]}"
    )
    sent = parse_sentiment(raw)
    assert len(sent["moments"]) == 2
    assert sent["moments"][0]["polarity"] == "negative"
    assert sent["moments"][1]["polarity"] == "positive"
    assert sent["moments"][0]["end_sec"] == 18.0


def test_parse_sentiment_legacy_flags_as_negative_moments() -> None:
    sent = parse_sentiment(
        '{"label": "negative", "score": 0.2, "flags": [{"start_sec": 5, "reason": "angry"}]}'
    )
    assert len(sent["moments"]) == 1
    assert sent["moments"][0]["polarity"] == "negative"
    assert has_negative_sentiment_moments(sent)


def test_sentiment_moments_reads_legacy_flags() -> None:
    stored = {"flags": [{"start_sec": 1.0, "reason": "issue"}]}
    moments = sentiment_moments(stored)
    assert len(moments) == 1
    assert moments[0]["polarity"] == "negative"


def test_normalize_category() -> None:
    assert normalize_category('"Cancellation Request"') == "Cancellation Request"
    assert normalize_category("") == "Uncategorized"


def test_summary_lines() -> None:
    assert summary_lines("a\n\nb") == ["a", "b"]
