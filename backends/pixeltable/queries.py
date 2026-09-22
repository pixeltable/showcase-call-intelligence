"""Declarative @pxt.query functions for FastAPIRouter serving."""

from __future__ import annotations

import functions
import pixeltable as pxt
from pixeltable.functions.string import contains

from schema import Calls, CoachingComments, TranscriptSegments

calls = Calls
segments = TranscriptSegments
comments = CoachingComments


def visible_status():
    """Query expression: surface column errors without changing the stored formula."""
    return functions.display_status(
        calls.pipeline_status,
        calls.diarized.errormsg,
        calls.summary.errormsg,
        calls.sentiment.errormsg,
        calls.action_items.errormsg,
        calls.category.errormsg,
        calls.qa_scorecard.errormsg,
    )


def collect_query(query_fn, /, **kwargs) -> list[dict]:
    """Execute a @pxt.query function and return row dicts."""
    from pixeltable.runtime import get_runtime

    template_query = query_fn.template_query
    with get_runtime().catalog.begin_xact(for_write=False, read_tvps=template_query._from_clause.tvps):
        rows = list(template_query._collect(args=kwargs))
    return [dict(row) for row in rows]


@pxt.query
def list_calls(agent_id: str = "", queue: str = "", min_handle_time: float = -1.0, limit: int = 50):
    return (
        calls.select(
            uuid=calls.uuid,
            call_date=calls.call_date,
            agent_id=calls.agent_id,
            customer_id=calls.customer_id,
            queue=calls.queue,
            vertical=calls.vertical,
            duration_sec=calls.duration_sec,
            handle_time_sec=calls.handle_time_sec,
            summary=calls.summary,
            category=calls.category,
            pipeline_status=visible_status(),
            sentiment=calls.sentiment,
            media_type=calls.media_type,
            original_filename=calls.original_filename,
            has_video_source=functions.has_video_source(calls.media_type, calls.video),
            diarized_err=calls.diarized.errormsg,
            summary_err=calls.summary.errormsg,
            sentiment_err=calls.sentiment.errormsg,
            action_items_err=calls.action_items.errormsg,
            category_err=calls.category.errormsg,
            qa_err=calls.qa_scorecard.errormsg,
        )
        .where(
            ((agent_id == "") | (calls.agent_id == agent_id))
            & ((queue == "") | (calls.queue == queue))
            & ((min_handle_time < 0) | (calls.handle_time_sec >= min_handle_time))
        )
        .order_by(calls.call_date, asc=False)
        .limit(limit)
    )


@pxt.query
def get_call(uuid: pxt.UUID):
    return calls.where(calls.uuid == uuid).select(
        uuid=calls.uuid,
        call_date=calls.call_date,
        agent_id=calls.agent_id,
        customer_id=calls.customer_id,
        queue=calls.queue,
        vertical=calls.vertical,
        media_type=calls.media_type,
        duration_sec=calls.duration_sec,
        handle_time_sec=calls.handle_time_sec,
        summary=calls.summary,
        category=calls.category,
        pipeline_status=visible_status(),
        sentiment=calls.sentiment,
        action_items=calls.action_items,
        qa_scorecard=calls.qa_scorecard,
        segments=calls.segments,
        diarized_err=calls.diarized.errormsg,
        summary_err=calls.summary.errormsg,
        sentiment_err=calls.sentiment.errormsg,
        action_items_err=calls.action_items.errormsg,
        category_err=calls.category.errormsg,
        qa_err=calls.qa_scorecard.errormsg,
        original_filename=calls.original_filename,
        has_video_source=functions.has_video_source(calls.media_type, calls.video),
        audio_url=calls.source_audio.fileurl,
        video_url=calls.video.fileurl,
    )


@pxt.query
def flagged_calls(limit: int = 50):
    return (
        calls.where(
            (calls.pipeline_status == "completed") & functions.is_flagged_sentiment(calls.sentiment)
        )
        .select(
            uuid=calls.uuid,
            call_date=calls.call_date,
            agent_id=calls.agent_id,
            customer_id=calls.customer_id,
            queue=calls.queue,
            vertical=calls.vertical,
            duration_sec=calls.duration_sec,
            handle_time_sec=calls.handle_time_sec,
            summary=calls.summary,
            category=calls.category,
            pipeline_status=visible_status(),
            sentiment=calls.sentiment,
            media_type=calls.media_type,
            original_filename=calls.original_filename,
            has_video_source=functions.has_video_source(calls.media_type, calls.video),
            diarized_err=calls.diarized.errormsg,
            summary_err=calls.summary.errormsg,
            sentiment_err=calls.sentiment.errormsg,
            action_items_err=calls.action_items.errormsg,
            category_err=calls.category.errormsg,
            qa_err=calls.qa_scorecard.errormsg,
        )
        .order_by(calls.call_date, asc=False)
        .limit(limit)
    )


@pxt.query
def keyword_search(query_text: str, limit: int = 20):
    return (
        segments.where(
            contains(segments.text, query_text, case=False) & (segments.pipeline_status == "completed")
        )
        .order_by(segments.call_date, asc=False)
        .limit(limit)
        .select(
            text=segments.text,
            call_uuid=segments.uuid,
            segment_pos=segments.pos,
            speaker=segments.speaker,
            start_sec=segments.start_sec,
            end_sec=segments.end_sec,
            agent_id=segments.agent_id,
            customer_id=segments.customer_id,
            queue=segments.queue,
            call_date=segments.call_date,
            media_type=segments.media_type,
            original_filename=segments.original_filename,
        )
    )


@pxt.query
def semantic_search(query_text: str, limit: int = 20):
    sim = segments.text.similarity(string=query_text)
    return (
        segments.where(segments.pipeline_status == "completed")
        .order_by(sim, asc=False)
        .limit(limit)
        .select(
            text=segments.text,
            call_uuid=segments.uuid,
            segment_pos=segments.pos,
            speaker=segments.speaker,
            start_sec=segments.start_sec,
            end_sec=segments.end_sec,
            agent_id=segments.agent_id,
            customer_id=segments.customer_id,
            queue=segments.queue,
            call_date=segments.call_date,
            media_type=segments.media_type,
            original_filename=segments.original_filename,
            score=sim,
        )
    )


@pxt.query
def comments_for_call(call_uuid: pxt.UUID):
    return (
        comments.where(comments.call_uuid == call_uuid)
        .select(
            uuid=comments.uuid,
            call_uuid=comments.call_uuid,
            segment_pos=comments.segment_pos,
            start_sec=comments.start_sec,
            author=comments.author,
            comment=comments.comment,
            timestamp=comments.timestamp,
        )
        .order_by(comments.timestamp, asc=True)
    )


@pxt.query
def call_playback_audio(uuid: pxt.UUID):
    return calls.where(calls.uuid == uuid).select(
        media=calls.source_audio,
    )


@pxt.query
def call_playback_video(uuid: pxt.UUID):
    return calls.where(calls.uuid == uuid).select(media=calls.video)
