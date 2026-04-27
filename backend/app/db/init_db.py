"""Inicializace DB — vytvoří tabulky.

pgvector extension (CREATE EXTENSION vector) musí existovat předem —
vytvoř ji ručně jako superuser:
  psql -U postgres -d dautuu -c "CREATE EXTENSION IF NOT EXISTS vector;"

Spouští se automaticky při startu backendu.
"""
from app.db.session import engine, Base
# Import modelů, aby byly registrovány v Base.metadata
import app.db.models  # noqa: F401


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_xai_pricing()


async def _seed_xai_pricing() -> None:
    """Vloží ceník xAI / Grok modelů do tabulky model_pricing.

    Používá INSERT ... ON CONFLICT DO NOTHING — bezpečné pro opakované spuštění.
    Zdroj: https://docs.x.ai/docs/models (duben 2026)
    """
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    XAI_MODELS = [
        # (model_id, display_name, input_$/1M, output_$/1M)
        # Skutečná ID dle xAI API (ověřeno duben 2026)
        ("grok-4-1-fast-non-reasoning",  "Grok 4.1 Fast",              0.80,  4.00),
        ("grok-4-1-fast-reasoning",      "Grok 4.1 Fast (reasoning)",  0.80,  4.00),
        ("grok-4-0709",                  "Grok 4",                     3.00, 15.00),
        ("grok-4-fast-non-reasoning",    "Grok 4 Fast",                5.00, 25.00),
        ("grok-4-fast-reasoning",        "Grok 4 Fast (reasoning)",    5.00, 25.00),
        ("grok-4.20-0309-non-reasoning", "Grok 4.20",                  3.00, 15.00),
        ("grok-4.20-0309-reasoning",     "Grok 4.20 (reasoning)",      3.00, 15.00),
        ("grok-4.20-multi-agent-0309",   "Grok 4.20 Multi-Agent",      3.00, 15.00),
        ("grok-3",                       "Grok 3",                     3.00, 15.00),
        ("grok-3-mini",                  "Grok 3 Mini",                0.30,  0.50),
        ("grok-code-fast-1",             "Grok Code Fast",             0.80,  4.00),
    ]

    async with AsyncSessionLocal() as db:
        for model_id, display_name, input_price, output_price in XAI_MODELS:
            await db.execute(
                text("""
                    INSERT INTO model_pricing
                        (provider, model, display_name, input_price_usd_per_m,
                         output_price_usd_per_m, source, synced_at)
                    VALUES
                        (:provider, :model, :display_name, :input_price,
                         :output_price, 'manual', NOW())
                    ON CONFLICT (provider, model) DO NOTHING
                """),
                {
                    "provider": "xai",
                    "model": model_id,
                    "display_name": display_name,
                    "input_price": input_price,
                    "output_price": output_price,
                },
            )
        await db.commit()
