"""Usage API — přehled spotřeby tokenů a nákladů."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import UsageLog, User
from app.db.session import get_db

router = APIRouter(prefix="/usage", tags=["usage"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ModelStats(BaseModel):
    provider: str
    model: str
    operation: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class DailyStats(BaseModel):
    day: str          # YYYY-MM-DD
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class SearchStats(BaseModel):
    """Souhrnné statistiky web search requestů."""
    total_requests: int
    total_results: int       # součet num_results přes všechny requesty
    cost_usd: float | None


class UsageStats(BaseModel):
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float | None
    by_model: list[ModelStats]
    by_day: list[DailyStats]
    web_search: SearchStats


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=UsageStats)
async def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Vrátí souhrnné statistiky spotřeby pro aktuálního uživatele."""

    # Agregace per model + operation
    model_result = await db.execute(
        select(
            UsageLog.provider,
            UsageLog.model,
            UsageLog.operation,
            func.count(UsageLog.id).label("calls"),
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            func.sum(UsageLog.cost_usd).label("cost_usd"),
        )
        .where(UsageLog.user_id == current_user.id)
        .group_by(UsageLog.provider, UsageLog.model, UsageLog.operation)
        .order_by(func.sum(UsageLog.cost_usd).desc().nulls_last())
    )
    model_rows = model_result.all()

    # Agregace per den (posledních 30 dní)
    day_result = await db.execute(
        select(
            func.date(UsageLog.created_at).label("day"),
            func.count(UsageLog.id).label("calls"),
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            func.sum(UsageLog.cost_usd).label("cost_usd"),
        )
        .where(UsageLog.user_id == current_user.id)
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at).desc())
        .limit(30)
    )
    day_rows = day_result.all()

    # Celkové součty
    total_result = await db.execute(
        select(
            func.count(UsageLog.id).label("calls"),
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            func.sum(UsageLog.cost_usd).label("cost_usd"),
        )
        .where(UsageLog.user_id == current_user.id)
    )
    totals = total_result.one()

    # Web search statistiky
    search_result = await db.execute(
        select(
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.units), 0).label("total_results"),
            func.sum(UsageLog.cost_usd).label("cost_usd"),
        )
        .where(
            UsageLog.user_id == current_user.id,
            UsageLog.operation == "web_search",
        )
    )
    search_totals = search_result.one()

    def _cost(val: Decimal | None) -> float | None:
        return float(val) if val is not None else None

    return UsageStats(
        total_calls=totals.calls or 0,
        total_input_tokens=totals.input_tokens or 0,
        total_output_tokens=totals.output_tokens or 0,
        total_cost_usd=_cost(totals.cost_usd),
        by_model=[
            ModelStats(
                provider=r.provider,
                model=r.model,
                operation=r.operation,
                calls=r.calls,
                input_tokens=r.input_tokens or 0,
                output_tokens=r.output_tokens or 0,
                cost_usd=_cost(r.cost_usd),
            )
            for r in model_rows
        ],
        by_day=[
            DailyStats(
                day=str(r.day),
                calls=r.calls,
                input_tokens=r.input_tokens or 0,
                output_tokens=r.output_tokens or 0,
                cost_usd=_cost(r.cost_usd),
            )
            for r in day_rows
        ],
        web_search=SearchStats(
            total_requests=search_totals.requests or 0,
            total_results=int(search_totals.total_results or 0),
            cost_usd=_cost(search_totals.cost_usd),
        ),
    )
