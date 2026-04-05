"""Usage logger — ukládá záznamy o spotřebě do tabulky usage_logs."""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageLog
from app.services.usage.pricing import get_chat_cost, get_embedding_cost, get_search_cost
from app.services.usage.pricing_sync import get_chat_cost_from_db

log = logging.getLogger("dautuu.usage")


async def log_chat_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
) -> None:
    """Zaznamená spotřebu tokenů a cenu pro jedno chat volání."""
    # Primárně cena z DB (aktuální, synchronizovaná při startu)
    cost = await get_chat_cost_from_db(provider, model, input_tokens, output_tokens)
    # Fallback na hardcoded ceník pokud DB cena chybí
    if cost is None:
        cost = get_chat_cost(provider, model, input_tokens, output_tokens)
    entry = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        operation="chat",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
        log.info(
            "USAGE chat provider=%s model=%s in=%d out=%d cost=$%.6f",
            provider, model, input_tokens, output_tokens, cost or 0,
        )
    except Exception as exc:
        log.error("USAGE_LOG_ERROR chat: %s", exc)
        await db.rollback()


async def log_embedding_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    user_id: UUID | None = None,
) -> None:
    """Zaznamená spotřebu tokenů a cenu pro embedding volání."""
    cost = get_embedding_cost(provider, model, input_tokens)
    entry = UsageLog(
        user_id=user_id,
        operation="embedding",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=None,
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
        log.debug(
            "USAGE embedding provider=%s model=%s tokens=%d cost=$%.6f",
            provider, model, input_tokens, cost or 0,
        )
    except Exception as exc:
        log.error("USAGE_LOG_ERROR embedding: %s", exc)
        await db.rollback()


# Placeholder pro budoucí modality
async def log_image_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    num_images: int,
    cost_per_image: float | None = None,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> None:
    from app.services.usage.pricing import IMAGE_PRICING
    price = cost_per_image or IMAGE_PRICING.get(provider, {}).get(model)
    cost = price * num_images if price is not None else None
    entry = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        operation="image",
        provider=provider,
        model=model,
        units=Decimal(str(num_images)),
        units_type="images",
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception as exc:
        log.error("USAGE_LOG_ERROR image: %s", exc)
        await db.rollback()


async def log_tts_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    characters: int,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> None:
    from app.services.usage.pricing import TTS_PRICING
    price_per_m = TTS_PRICING.get(provider, {}).get(model)
    cost = characters * price_per_m / 1_000_000 if price_per_m is not None else None
    entry = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        operation="tts",
        provider=provider,
        model=model,
        units=Decimal(str(characters)),
        units_type="characters",
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception as exc:
        log.error("USAGE_LOG_ERROR tts: %s", exc)
        await db.rollback()


async def log_stt_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    duration_seconds: float,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> None:
    from app.services.usage.pricing import STT_PRICING
    price_per_min = STT_PRICING.get(provider, {}).get(model)
    minutes = duration_seconds / 60
    cost = minutes * price_per_min if price_per_min is not None else None
    entry = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        operation="stt",
        provider=provider,
        model=model,
        units=Decimal(str(round(duration_seconds, 2))),
        units_type="seconds",
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception as exc:
        log.error("USAGE_LOG_ERROR stt: %s", exc)
        await db.rollback()


async def log_search_usage(
    db: AsyncSession,
    *,
    query: str,
    provider: str = "tavily",
    search_depth: str = "basic",
    num_results: int = 0,
    success: bool = True,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> None:
    """Zaznamená jeden web search request — query, výsledky, cenu."""
    cost = get_search_cost(provider, search_depth, num_requests=1)
    entry = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        operation="web_search",
        provider=provider,
        model=search_depth,          # basic | advanced — jako "model"
        query_text=query,
        units=Decimal(str(num_results)),
        units_type="results",
        cost_usd=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(entry)
    try:
        await db.commit()
        log.info(
            "USAGE web_search provider=%s depth=%s results=%d success=%s cost=$%.6f query=%r",
            provider, search_depth, num_results, success, cost or 0, query,
        )
    except Exception as exc:
        log.error("USAGE_LOG_ERROR web_search: %s", exc)
        await db.rollback()
