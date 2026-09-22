"""Vertical profiles — prompts and UI labels per use case (call center, sales, podcast, interview)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerticalId = Literal["call_center", "sales", "podcast", "interview"]

DEFAULT_VERTICAL: VerticalId = "call_center"
VALID_VERTICALS: frozenset[str] = frozenset({"call_center", "sales", "podcast", "interview"})


@dataclass(frozen=True)
class EnrichmentPrompts:
    summary: str
    action_items: str
    sentiment: str
    category: str
    qa: str


@dataclass(frozen=True)
class VerticalLabels:
    upload_title: str
    agent_id: str
    customer_id: str
    queue: str
    roster_agent: str
    roster_customer: str
    roster_queue: str
    qa_empathy: str
    qa_resolution: str
    qa_compliance: str
    qa_overall: str
    kpi_recordings: str
    kpi_duration: str


@dataclass(frozen=True)
class VerticalProfile:
    id: VerticalId
    display_name: str
    prompts: EnrichmentPrompts
    labels: VerticalLabels
    speaker_display: dict[str, str]


def normalize_vertical(vertical: str | None) -> VerticalId:
    if vertical and vertical in VALID_VERTICALS:
        return vertical  # type: ignore[return-value]
    return DEFAULT_VERTICAL


_CALL_CENTER = VerticalProfile(
    id="call_center",
    display_name="Call Center",
    prompts=EnrichmentPrompts(
        summary=(
            "Summarize this call center recording for a supervisor. "
            'Return ONLY JSON with key "bullets": an array of 3-5 plain-English strings. '
            "Cover the customer issue, what the agent did, and any follow-up. "
            "No markdown, no labels, no preamble."
        ),
        action_items=(
            "Extract action items from this call. Include agent commitments such as emails, "
            "callbacks, credits, escalations, or follow-up tasks. "
            "Return ONLY a JSON array of strings. Use an empty array only if there are truly none."
        ),
        sentiment=(
            "Analyze call sentiment for QA. The transcript includes [start-end] timestamps. "
            'Return ONLY JSON with keys: '
            '"label" (positive|neutral|negative), "score" (0.0-1.0, lower is worse), '
            '"rationale" (string), '
            '"moments" (array of objects with "start_sec", optional "end_sec", '
            '"polarity" (positive|neutral|negative), and "reason" for notable moments). '
            "Include 0-N moments per polarity where transcript evidence exists. "
            "No explanation outside the JSON."
        ),
        category=(
            'Classify this call into one short category label '
            '(e.g. "Billing Dispute", "Cancellation Request"). '
            "Return ONLY the category name. No explanation."
        ),
        qa=(
            'Score this call for QA. Return ONLY JSON with numeric keys '
            '"empathy", "resolution", "compliance", "overall" (0-10 each) '
            'and a short "notes" string. No explanation outside the JSON.'
        ),
    ),
    labels=VerticalLabels(
        upload_title="Upload Call",
        agent_id="Agent ID",
        customer_id="Customer ID",
        queue="Queue",
        roster_agent="Agent",
        roster_customer="Customer",
        roster_queue="Queue",
        qa_empathy="Empathy",
        qa_resolution="Resolution",
        qa_compliance="Compliance",
        qa_overall="Overall",
        kpi_recordings="Calls (7d)",
        kpi_duration="Avg handle (sec)",
    ),
    speaker_display={"AGENT": "Agent", "CUSTOMER": "Customer"},
)

_SALES = VerticalProfile(
    id="sales",
    display_name="Sales Call",
    prompts=EnrichmentPrompts(
        summary=(
            "Summarize this sales conversation for a sales manager. "
            'Return ONLY JSON with key "bullets": an array of 3-5 plain-English strings. '
            "Cover the prospect's situation, objections raised, what the rep did, and agreed next steps. "
            "No markdown, no labels, no preamble."
        ),
        action_items=(
            "Extract follow-ups from this sales call: demos scheduled, proposals to send, "
            "stakeholders to loop in, pricing follow-ups, or other rep commitments. "
            "Return ONLY a JSON array of strings. Use an empty array only if there are truly none."
        ),
        sentiment=(
            "Analyze buyer sentiment and engagement. The transcript includes [start-end] timestamps. "
            'Return ONLY JSON with keys: '
            '"label" (positive|neutral|negative), "score" (0.0-1.0, higher is more engaged/buying signal), '
            '"rationale" (string), '
            '"moments" (array of objects with "start_sec", optional "end_sec", '
            '"polarity" (positive|neutral|negative), and "reason" for notable moments). '
            "Include 0-N moments per polarity where transcript evidence exists. "
            "No explanation outside the JSON."
        ),
        category=(
            'Classify this sales call into one short stage label '
            '(e.g. "Discovery", "Demo", "Negotiation", "Closing"). '
            "Return ONLY the category name. No explanation."
        ),
        qa=(
            'Score this sales call. Return ONLY JSON with numeric keys '
            '"empathy", "resolution", "compliance", "overall" (0-10 each) '
            '(interpret empathy as rapport, resolution as advancing the deal, compliance as accurate claims) '
            'and a short "notes" string. No explanation outside the JSON.'
        ),
    ),
    labels=VerticalLabels(
        upload_title="Upload Sales Call",
        agent_id="Rep ID",
        customer_id="Prospect ID",
        queue="Pipeline stage",
        roster_agent="Rep",
        roster_customer="Prospect",
        roster_queue="Stage",
        qa_empathy="Rapport",
        qa_resolution="Deal progress",
        qa_compliance="Accurate claims",
        qa_overall="Overall",
        kpi_recordings="Calls (7d)",
        kpi_duration="Avg duration (sec)",
    ),
    speaker_display={"AGENT": "Rep", "CUSTOMER": "Prospect"},
)

_PODCAST = VerticalProfile(
    id="podcast",
    display_name="Podcast / Media",
    prompts=EnrichmentPrompts(
        summary=(
            "Summarize this podcast or media recording for a producer. "
            'Return ONLY JSON with key "bullets": an array of 3-5 plain-English strings. '
            "Cover main themes, notable quotes or moments, and any editorial highlights. "
            "No markdown, no labels, no preamble."
        ),
        action_items=(
            "Extract production or editorial follow-ups: clips to publish, guests to rebook, "
            "fact-checks, show notes tasks, or social clips. "
            "Return ONLY a JSON array of strings. Use an empty array only if there are truly none."
        ),
        sentiment=(
            "Analyze tone and audience engagement across the recording. "
            "The transcript includes [start-end] timestamps. "
            'Return ONLY JSON with keys: '
            '"label" (positive|neutral|negative), "score" (0.0-1.0), '
            '"rationale" (string), '
            '"moments" (array of objects with "start_sec", optional "end_sec", '
            '"polarity" (positive|neutral|negative), and "reason" for notable moments). '
            "Include 0-N moments per polarity where transcript evidence exists. "
            "No explanation outside the JSON."
        ),
        category=(
            'Classify this episode into one short topic label '
            '(e.g. "Technology", "Culture", "Business"). '
            "Return ONLY the category name. No explanation."
        ),
        qa=(
            'Score this recording for production quality. Return ONLY JSON with numeric keys '
            '"empathy", "resolution", "compliance", "overall" (0-10 each) '
            '(interpret empathy as host/guest chemistry, resolution as clarity of message, '
            "compliance as factual care, overall as listenability) "
            'and a short "notes" string. No explanation outside the JSON.'
        ),
    ),
    labels=VerticalLabels(
        upload_title="Upload Recording",
        agent_id="Host",
        customer_id="Guest / Show",
        queue="Series",
        roster_agent="Host",
        roster_customer="Guest",
        roster_queue="Series",
        qa_empathy="Chemistry",
        qa_resolution="Clarity",
        qa_compliance="Factual care",
        qa_overall="Listenability",
        kpi_recordings="Recordings (7d)",
        kpi_duration="Avg duration (sec)",
    ),
    speaker_display={"AGENT": "Host", "CUSTOMER": "Guest"},
)

_INTERVIEW = VerticalProfile(
    id="interview",
    display_name="Interview",
    prompts=EnrichmentPrompts(
        summary=(
            "Summarize this interview for a hiring manager. "
            'Return ONLY JSON with key "bullets": an array of 3-5 plain-English strings. '
            "Cover candidate strengths, concerns or gaps, and recommended next steps. "
            "No markdown, no labels, no preamble."
        ),
        action_items=(
            "Extract interview follow-ups: reference checks, take-home assignments, "
            "panel interviews, feedback deadlines, or recruiter tasks. "
            "Return ONLY a JSON array of strings. Use an empty array only if there are truly none."
        ),
        sentiment=(
            "Analyze candidate tone and interview dynamics. The transcript includes [start-end] timestamps. "
            'Return ONLY JSON with keys: '
            '"label" (positive|neutral|negative), "score" (0.0-1.0), '
            '"rationale" (string), '
            '"moments" (array of objects with "start_sec", optional "end_sec", '
            '"polarity" (positive|neutral|negative), and "reason" for notable moments). '
            "Include 0-N moments per polarity where transcript evidence exists. "
            "No explanation outside the JSON."
        ),
        category=(
            'Classify this interview into one short type label '
            '(e.g. "Behavioral", "Technical", "Culture Fit"). '
            "Return ONLY the category name. No explanation."
        ),
        qa=(
            'Score this interview for hiring quality. Return ONLY JSON with numeric keys '
            '"empathy", "resolution", "compliance", "overall" (0-10 each) '
            '(interpret empathy as candidate rapport, resolution as answer depth, '
            "compliance as fair/legal questioning, overall as hire signal) "
            'and a short "notes" string. No explanation outside the JSON.'
        ),
    ),
    labels=VerticalLabels(
        upload_title="Upload Interview",
        agent_id="Interviewer",
        customer_id="Candidate",
        queue="Role",
        roster_agent="Interviewer",
        roster_customer="Candidate",
        roster_queue="Role",
        qa_empathy="Rapport",
        qa_resolution="Answer depth",
        qa_compliance="Fair process",
        qa_overall="Hire signal",
        kpi_recordings="Interviews (7d)",
        kpi_duration="Avg duration (sec)",
    ),
    speaker_display={"AGENT": "Interviewer", "CUSTOMER": "Candidate"},
)

_PROFILES: dict[str, VerticalProfile] = {
    p.id: p for p in (_CALL_CENTER, _SALES, _PODCAST, _INTERVIEW)
}


def get_profile(vertical: str | None) -> VerticalProfile:
    key = normalize_vertical(vertical)
    return _PROFILES[key]


def list_profiles() -> list[VerticalProfile]:
    return [_PROFILES[k] for k in ("call_center", "sales", "podcast", "interview")]
