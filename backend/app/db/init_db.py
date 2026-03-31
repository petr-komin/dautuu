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
