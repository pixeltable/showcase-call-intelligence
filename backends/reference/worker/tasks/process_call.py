from __future__ import annotations

import uuid

from app.config import settings
from worker.celery_app import celery_app


@celery_app.task(
    name="worker.tasks.process_call",
    soft_time_limit=settings.celery_task_soft_time_limit_sec,
    time_limit=settings.celery_task_time_limit_sec,
)
def process_call(call_id: str) -> None:
    from pathlib import Path

    from app.database import SessionLocal
    from app.models import Call, TranscriptSegment
    from app.services.diarization import extract_segments, flatten_transcript
    from app.services.ollama_client import OllamaClient
    from app.services.video import extract_audio_from_video
    from app.services.whisperx_service import transcribe_diarize
    from worker.tasks.embed_maintenance import embed_call_segments

    db = SessionLocal()
    try:
        call = db.get(Call, uuid.UUID(call_id))
        if not call:
            return

        call.status = "transcribing"
        db.commit()

        if call.video_path and not Path(call.audio_path).is_file():
            extract_audio_from_video(Path(call.video_path), Path(call.audio_path))
        diarized = transcribe_diarize(call.audio_path)

        call.status = "diarizing"
        db.commit()

        labeled = extract_segments(diarized)

        db.query(TranscriptSegment).filter(TranscriptSegment.call_id == call.id).delete()
        for pos, seg in enumerate(labeled):
            db.add(
                TranscriptSegment(
                    call_id=call.id,
                    speaker=seg.speaker,
                    start_sec=seg.start_sec,
                    end_sec=seg.end_sec,
                    text=seg.text,
                    pos=pos,
                )
            )

        if labeled:
            call.handle_time_sec = max(s.end_sec for s in labeled)
            call.duration_sec = call.handle_time_sec
        else:
            call.handle_time_sec = 0.0
            call.duration_sec = 0.0

        call.status = "enriching"
        db.commit()

        transcript_text = flatten_transcript(labeled)
        client = OllamaClient()
        result = client.enrich_call(transcript_text, vertical=call.vertical or "call_center")
        call.summary = result.summary
        call.action_items = result.action_items
        call.sentiment = result.sentiment
        call.category = result.category
        call.qa_scorecard = result.qa_scorecard

        call.status = "embedding"
        db.commit()

        embed_call_segments(db, call.id)

        call.status = "completed"
        call.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        call = db.get(Call, uuid.UUID(call_id))
        if call:
            call.status = "failed"
            call.error_message = str(exc)
            db.commit()
        raise exc
    finally:
        db.close()
