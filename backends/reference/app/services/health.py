"""Dependency health checks for the Reference backend."""

from __future__ import annotations

import httpx
import redis
from sqlalchemy import text

from app.config import settings
from app.database import engine
from call_center_api.schemas import HealthCheckResult, HealthResponse
from worker.celery_app import celery_app


def _ollama_check() -> HealthCheckResult:
    host = settings.ollama_host.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{host}/api/tags")
        if resp.status_code != 200:
            return HealthCheckResult(ok=False, detail=f"HTTP {resp.status_code}")
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        required = settings.ollama_model if ":" in settings.ollama_model else f"{settings.ollama_model}:latest"
        if required not in names:
            return HealthCheckResult(ok=False, detail=f"Missing model: {required}")
        return HealthCheckResult(ok=True, detail=f"Models available at {host}")
    except httpx.HTTPError as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def _postgres_check() -> HealthCheckResult:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return HealthCheckResult(ok=True)
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def _redis_check() -> HealthCheckResult:
    client = None
    try:
        client = redis.from_url(settings.redis_url)
        client.ping()
        return HealthCheckResult(ok=True)
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))
    finally:
        if client is not None:
            client.close()


def _celery_check() -> HealthCheckResult:
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        active = inspect.active()
        if not active:
            return HealthCheckResult(ok=False, detail="No Celery workers responding")
        workers = ", ".join(sorted(active.keys()))
        return HealthCheckResult(ok=True, detail=f"{len(active)} worker(s): {workers}")
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def _embed_model_check() -> HealthCheckResult:
    try:
        import importlib.util

        if importlib.util.find_spec("sentence_transformers") is None:
            raise ImportError("sentence_transformers not installed")
        return HealthCheckResult(ok=True, detail=settings.embed_model)
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def build_health_response() -> HealthResponse:
    checks = {
        "postgres": _postgres_check(),
        "redis": _redis_check(),
        "celery": _celery_check(),
        "ollama": _ollama_check(),
        "embed_model": _embed_model_check(),
    }
    status = "ok" if all(c.ok for c in checks.values()) else "degraded"
    return HealthResponse(status=status, backend="reference", checks=checks)
