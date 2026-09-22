"""Dev-only admin endpoints for embedding maintenance."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Call
from worker.tasks.embed_maintenance import backfill_embeddings, reembed_call
from worker.tasks.resume_call import resume_call_processing

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin_enabled() -> None:
    if not settings.enable_admin_endpoints:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/reembed/{call_id}")
def trigger_reembed(call_id: uuid.UUID, db: Session = Depends(get_db)):
    _require_admin_enabled()
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    task = reembed_call.delay(str(call_id))
    return {"task_id": task.id, "call_id": str(call_id)}


@router.post("/backfill-embeddings")
def trigger_backfill(limit: int = 100):
    _require_admin_enabled()
    task = backfill_embeddings.delay(limit=limit)
    return {"task_id": task.id, "limit": limit}


@router.post("/resume/{call_id}")
def trigger_resume(call_id: uuid.UUID, db: Session = Depends(get_db)):
    _require_admin_enabled()
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    task = resume_call_processing.delay(str(call_id))
    return {"task_id": task.id, "call_id": str(call_id), "status": call.status}
