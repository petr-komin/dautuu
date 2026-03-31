"""Embedding service — převod textu na vektory."""
from __future__ import annotations

import logging
from app.core.config import settings

log = logging.getLogger("dautuu.embeddings")

# Přibližný limit: model intfloat/multilingual-e5-large-instruct má 512 tokenů.
# Czech/multilingual text: ~3.2 chars/token → 512 tokens ≈ 1638 chars.
# Bezpečně zkrátíme na 1400 znaků.
_MAX_CHARS = 1400


async def embed(text: str, db=None) -> list[float]:
    """Vrátí embedding vektor pro zadaný text.

    db: volitelná AsyncSession — pokud je předána, zaloguje usage do DB.
    """
    text = text.strip()
    if not text:
        raise ValueError("Nelze embedovat prázdný text")
    if len(text) > _MAX_CHARS:
        log.debug("EMBED_TRUNCATE original_len=%d -> %d", len(text), _MAX_CHARS)
        text = text[:_MAX_CHARS]

    if settings.embedding_provider == "together":
        return await _embed_together(text, db=db)

    raise ValueError(f"Neznámý embedding provider: {settings.embedding_provider}")


async def embed_batch(texts: list[str], db=None) -> list[list[float]]:
    """Vrátí embeddingy pro více textů najednou.

    db: volitelná AsyncSession — pokud je předána, zaloguje usage do DB.
    """
    texts = [t.strip()[:_MAX_CHARS] for t in texts]
    if settings.embedding_provider == "together":
        return await _embed_together_batch(texts, db=db)
    raise ValueError(f"Neznámý embedding provider: {settings.embedding_provider}")


async def _embed_together(text: str, db=None) -> list[float]:
    from together import AsyncTogether
    client = AsyncTogether(api_key=settings.together_api_key)
    resp = await client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )
    if db is not None:
        try:
            from app.services.usage.logger import log_embedding_usage
            tokens = resp.usage.total_tokens if resp.usage else 0
            await log_embedding_usage(
                db,
                provider="together",
                model=settings.embedding_model,
                input_tokens=tokens,
            )
        except Exception as exc:
            log.error("EMBED_USAGE_LOG_ERROR: %s", exc)
    return resp.data[0].embedding


async def _embed_together_batch(texts: list[str], db=None) -> list[list[float]]:
    from together import AsyncTogether
    client = AsyncTogether(api_key=settings.together_api_key)
    resp = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    if db is not None:
        try:
            from app.services.usage.logger import log_embedding_usage
            tokens = resp.usage.total_tokens if resp.usage else 0
            await log_embedding_usage(
                db,
                provider="together",
                model=settings.embedding_model,
                input_tokens=tokens,
            )
        except Exception as exc:
            log.error("EMBED_USAGE_LOG_ERROR batch: %s", exc)
    # API vrací výsledky seřazené podle indexu
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
