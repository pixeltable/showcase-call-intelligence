"""Dependency health checks for the Pixeltable backend."""

from __future__ import annotations

import os

import config
import httpx
import pixeltable as pxt
from call_center_api.schemas import HealthCheckResult, HealthResponse


def _pixeltable_home() -> str:
    return os.path.expanduser(os.environ.get("PIXELTABLE_HOME", "~/.pixeltable"))


def _ollama_check() -> HealthCheckResult:
    host = config.OLLAMA_HOST.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{host}/api/tags")
        if resp.status_code != 200:
            return HealthCheckResult(ok=False, detail=f"HTTP {resp.status_code}")
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        missing: list[str] = []
        for required in (config.OLLAMA_MODEL,):
            base = required.split(":")[0]
            if not any(n == required or n.startswith(f"{base}:") for n in names):
                missing.append(required)
        if missing:
            return HealthCheckResult(ok=False, detail=f"Missing models: {', '.join(missing)}")
        return HealthCheckResult(ok=True, detail=f"Models available at {host}")
    except httpx.HTTPError as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def _catalog_check() -> HealthCheckResult:
    home = _pixeltable_home()
    try:
        pxt.get_table(f"{config.APP_NAMESPACE}.calls")
        return HealthCheckResult(ok=True, home=home)
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc), home=home)


def _pipeline_check() -> HealthCheckResult:
    try:
        calls = pxt.get_table(f"{config.APP_NAMESPACE}.calls")
        rows = calls.select(
            pipeline_status=calls.pipeline_status,
            diarized_err=calls.diarized.errormsg,
            summary_err=calls.summary.errormsg,
            sentiment_err=calls.sentiment.errormsg,
            action_items_err=calls.action_items.errormsg,
            category_err=calls.category.errormsg,
            qa_err=calls.qa_scorecard.errormsg,
        ).collect()
        failed = 0
        for row in rows:
            errors = [
                row.get("diarized_err"),
                row.get("summary_err"),
                row.get("sentiment_err"),
                row.get("action_items_err"),
                row.get("category_err"),
                row.get("qa_err"),
            ]
            if any(err and str(err).strip() for err in errors):
                failed += 1
            elif row.get("pipeline_status") == "failed":
                failed += 1
        if failed:
            return HealthCheckResult(ok=False, detail=f"{failed} call(s) in failed state")
        return HealthCheckResult(ok=True, detail=f"{len(rows)} call(s) in catalog")
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def _embed_model_check() -> HealthCheckResult:
    try:
        import importlib.util

        if importlib.util.find_spec("sentence_transformers") is None:
            raise ImportError("sentence_transformers not installed")
        return HealthCheckResult(ok=True, detail=config.EMBED_MODEL)
    except Exception as exc:
        return HealthCheckResult(ok=False, detail=str(exc))


def build_health_response() -> HealthResponse:
    checks = {
        "catalog": _catalog_check(),
        "ollama": _ollama_check(),
        "embed_model": _embed_model_check(),
        "pipeline": _pipeline_check(),
    }
    ok = all(c.ok for c in checks.values())
    return HealthResponse(status="ok" if ok else "degraded", backend="pixeltable", checks=checks)
