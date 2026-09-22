"""Local Hugging Face sentence-transformer embeddings for semantic search."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embed_model, device="cpu")
    return _model


def prewarm_embedder() -> None:
    """Load the sentence-transformer model once (e.g. on Celery worker startup)."""
    get_embedder()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = get_embedder().encode(texts, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]
