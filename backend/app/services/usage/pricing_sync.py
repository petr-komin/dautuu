"""Synchronizace ceníku modelů z API providerů do DB tabulky model_pricing.

Spouští se při startu backendu (lifespan). Pro každý provider kde máme API klíč
načte aktuální seznam modelů a jejich ceny a uloží/aktualizuje záznamy v DB.

Podporované providery:
  - Together AI  — /v1/models endpoint, vrátí pricing.input / pricing.output
  - (OpenAI a Anthropic zatím nemají veřejné pricing API)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ModelPricing
from app.db.session import AsyncSessionLocal

log = logging.getLogger("dautuu.pricing_sync")

_TOGETHER_MODELS_URL = "https://api.together.xyz/v1/models"
_HTTP_TIMEOUT = 15.0


async def sync_pricing() -> None:
    """Hlavní vstupní bod — zavolej z lifespan při startu."""
    async with AsyncSessionLocal() as db:
        updated = 0
        if settings.together_api_key:
            updated += await _sync_together(db)
        log.info("PRICING_SYNC done — upserted %d model rows", updated)


# ---------------------------------------------------------------------------
# Together AI
# ---------------------------------------------------------------------------

async def _sync_together(db: AsyncSession) -> int:
    """Načte modely z Together AI API a upsertuje ceny do DB. Vrátí počet upsertů."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                _TOGETHER_MODELS_URL,
                headers={"Authorization": f"Bearer {settings.together_api_key}"},
            )
            resp.raise_for_status()
            models: list[dict] = resp.json()
    except Exception as exc:
        log.warning("PRICING_SYNC together fetch FAILED: %s: %s — použiju DB cache", type(exc).__name__, exc)
        return 0

    now = datetime.now(timezone.utc)
    rows = []

    for m in models:
        model_id: str = m.get("id", "")
        if not model_id:
            continue

        pricing = m.get("pricing") or {}
        input_price = pricing.get("input")   # $/M tokenů, 0 = zdarma/neznámé
        output_price = pricing.get("output")
        display_name = m.get("display_name") or None

        # Přeskočíme modely kde Together API vrátí nulu pro obě ceny
        # (jsou to buď base modely, LoRA adaptery nebo modely bez veřejné ceny)
        # Výjimka: pokud je input > 0, vždy zahrneme.
        if (input_price is None or input_price == 0) and (output_price is None or output_price == 0):
            continue

        rows.append({
            "provider": "together",
            "model": model_id,
            "display_name": display_name,
            "input_price_usd_per_m": Decimal(str(input_price)) if input_price else None,
            "output_price_usd_per_m": Decimal(str(output_price)) if output_price else None,
            "units_price_usd": None,
            "units_type": None,
            "synced_at": now,
            "source": "together_api",
        })

    if not rows:
        log.warning("PRICING_SYNC together: API vrátilo 0 modelů s cenou")
        return 0

    # Upsert — aktualizuj pokud záznam existuje, vlož pokud ne
    stmt = pg_insert(ModelPricing).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_model_pricing_provider_model",
        set_={
            "display_name": stmt.excluded.display_name,
            "input_price_usd_per_m": stmt.excluded.input_price_usd_per_m,
            "output_price_usd_per_m": stmt.excluded.output_price_usd_per_m,
            "synced_at": stmt.excluded.synced_at,
            "source": stmt.excluded.source,
        },
    )
    await db.execute(stmt)
    await db.commit()

    log.info("PRICING_SYNC together: upserted %d models", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Načtení cen z DB (s in-memory cache)
# ---------------------------------------------------------------------------

# In-memory cache: {(provider, model): (input_per_m, output_per_m)}
# Naplní se při prvním dotazu, přetrvá po dobu životnosti procesu.
_cache: dict[tuple[str, str], tuple[Decimal | None, Decimal | None]] = {}
_cache_loaded = False


async def _ensure_cache(db: AsyncSession) -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    rows = await db.execute(select(ModelPricing))
    for row in rows.scalars():
        _cache[(row.provider, row.model)] = (row.input_price_usd_per_m, row.output_price_usd_per_m)
    _cache_loaded = True


async def get_chat_cost_from_db(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Načte cenu z DB cache. None pokud model v DB není."""
    global _cache_loaded

    # Pokud cache ještě není naplněna, načteme ji z DB
    if not _cache_loaded:
        try:
            async with AsyncSessionLocal() as db:
                await _ensure_cache(db)
        except Exception as exc:
            log.warning("PRICING_DB_CACHE load failed: %s", exc)
            return None

    prices = _cache.get((provider, model))
    if prices is None:
        # Zkusíme suffix fallback — stejná logika jako v hardcoded pricing.py
        for (p, m), v in _cache.items():
            if p == provider and (model.endswith(m) or m.endswith(model.split("/")[-1])):
                prices = v
                break

    if prices is None:
        return None

    input_p, output_p = prices
    if input_p is None and output_p is None:
        return None

    cost = (
        (float(input_p or 0) * input_tokens) +
        (float(output_p or 0) * output_tokens)
    ) / 1_000_000
    return cost


def invalidate_pricing_cache() -> None:
    """Vymaže in-memory cache — zavolej po sync_pricing() aby se ceny přenačetly."""
    global _cache, _cache_loaded
    _cache = {}
    _cache_loaded = False
