"""Tests for vertical profile registry."""

from call_center_api.verticals import (
    DEFAULT_VERTICAL,
    VALID_VERTICALS,
    get_profile,
    list_profiles,
    normalize_vertical,
)


def test_normalize_vertical_defaults_unknown() -> None:
    assert normalize_vertical(None) == DEFAULT_VERTICAL
    assert normalize_vertical("") == DEFAULT_VERTICAL
    assert normalize_vertical("invalid") == DEFAULT_VERTICAL


def test_normalize_vertical_accepts_known_ids() -> None:
    for vertical in VALID_VERTICALS:
        assert normalize_vertical(vertical) == vertical


def test_get_profile_returns_matching_prompts() -> None:
    sales = get_profile("sales")
    assert sales.id == "sales"
    assert "sales manager" in sales.prompts.summary.lower()
    assert sales.labels.qa_empathy == "Rapport"

    podcast = get_profile("podcast")
    assert "producer" in podcast.prompts.summary.lower()
    assert podcast.speaker_display["AGENT"] == "Host"


def test_get_profile_falls_back_to_call_center() -> None:
    profile = get_profile("not-a-vertical")
    assert profile.id == DEFAULT_VERTICAL
    assert "call center" in profile.prompts.summary.lower()


def test_list_profiles_covers_all_verticals() -> None:
    profiles = list_profiles()
    assert {p.id for p in profiles} == VALID_VERTICALS
