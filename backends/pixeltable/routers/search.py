"""Hybrid keyword + semantic search on transcript_segments view."""

from __future__ import annotations

import logging

import config
import queries
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_MAX_QUERY = min(config.MAX_QUERY_LENGTH, 500)


@router.get("")
def search_transcripts(
    q: str = Query(min_length=1, max_length=_MAX_QUERY),
    mode: str = Query(default="hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(default=20, le=100),
):
    query = q.strip()
    hits: list[dict] = []
    seen: set[tuple[str, int]] = set()

    if mode in ("keyword", "hybrid"):
        for row in queries.collect_query(queries.keyword_search, query_text=query, limit=limit):
            key = (str(row.get("call_uuid")), int(row.get("segment_pos", 0)))
            if key in seen:
                continue
            seen.add(key)
            row = dict(row)
            row["score"] = 1.0
            row["match_type"] = "keyword"
            hits.append(row)

    if mode in ("semantic", "hybrid") and len(hits) < limit:
        try:
            for row in queries.collect_query(queries.semantic_search, query_text=query, limit=limit):
                key = (str(row.get("call_uuid")), int(row.get("segment_pos", 0)))
                if key in seen:
                    continue
                seen.add(key)
                row = dict(row)
                if row.get("score") is None:
                    row["score"] = None
                row["match_type"] = "semantic"
                hits.append(row)
                if len(hits) >= limit:
                    break
        except Exception as exc:
            logger.warning("Semantic search failed: %s", exc)

    return hits[:limit]
