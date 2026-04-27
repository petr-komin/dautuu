from fastapi import APIRouter, Depends
from pydantic import BaseModel
import httpx

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.db.models import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/providers", tags=["providers"])


class ModelPreset(BaseModel):
    provider: str
    model: str
    label: str
    # Volitelné metadata pro UI
    slow: bool = False           # reasoning model — TTFT v desítkách sekund
    tier: str = "basic"          # "basic" nebo "advanced" (advanced se v UI skrývá)
    supports_search: bool = False  # provider má built-in web search (xAI Live Search, atd.)
    supports_reasoning_effort: bool = False  # model akceptuje reasoning_effort parametr


class ProviderInfo(BaseModel):
    id: str
    available: bool
    models: list[ModelPreset]


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]


class PreferenceRequest(BaseModel):
    provider: str
    model: str


class PreferenceResponse(BaseModel):
    provider: str
    model: str


async def get_together_models() -> list[ModelPreset]:
    """Načte serverless chat modely živě z Together API (pricing.input > 0)."""
    try:
        from together import AsyncTogether
        client = AsyncTogether(api_key=settings.together_api_key)
        all_models = await client.models.list()
        return [
            ModelPreset(provider="together", model=m.id, label=m.display_name or m.id)
            for m in all_models
            if m.type == "chat" and m.pricing and m.pricing.input > 0
        ]
    except Exception:
        return []


async def get_ollama_models() -> list[ModelPreset]:
    """Načte nainstalované modely z lokální Ollama instance."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
            return [
                ModelPreset(provider="ollama", model=m["name"], label=m["name"])
                for m in r.json().get("models", [])
            ]
    except Exception:
        return []


# Ruční metadata pro xAI modely — slow/tier/label.
# Klíč = model ID. Seznam se kříží s živým /v1/models, takže když xAI něco
# přidá/odebere, projeví se to automaticky; metadata zde slouží jen pro UI.
_XAI_MODEL_META: dict[str, dict] = {
    # Grok 4.1 série — primární doporučené
    "grok-4-1-fast-non-reasoning": {"label": "Grok 4.1 Fast",          "tier": "basic",    "slow": False},
    "grok-4-1-fast-reasoning":     {"label": "Grok 4.1 Fast (think)",  "tier": "advanced", "slow": True},
    # Grok 4 série
    "grok-4-0709":                 {"label": "Grok 4",                 "tier": "basic",    "slow": True},
    "grok-4-fast-non-reasoning":   {"label": "Grok 4 Fast",            "tier": "basic",    "slow": False},
    "grok-4-fast-reasoning":       {"label": "Grok 4 Fast (think)",    "tier": "advanced", "slow": True},
    # Grok 4.20 série
    "grok-4.20-0309-non-reasoning":  {"label": "Grok 4.20",             "tier": "advanced", "slow": False},
    "grok-4.20-0309-reasoning":      {"label": "Grok 4.20 (think)",     "tier": "advanced", "slow": True},
    "grok-4.20-multi-agent-0309":    {"label": "Grok 4.20 Multi-Agent", "tier": "advanced", "slow": True},
    # Grok 3
    "grok-3":                      {"label": "Grok 3",                 "tier": "advanced", "slow": False},
    "grok-3-mini":                 {"label": "Grok 3 Mini",            "tier": "advanced", "slow": True},
    # Code
    "grok-code-fast-1":            {"label": "Grok Code Fast",         "tier": "basic",    "slow": False},
}


async def get_xai_models() -> list[ModelPreset]:
    """Načte dostupné xAI modely živě z /v1/models a obohatí o lokální metadata.

    Pokud API selže, vrátí ručně udržovaný seznam z `_XAI_MODEL_META`.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {settings.xai_api_key}"},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            live_ids = {m["id"] for m in data if m.get("object") == "model"}
            # Bereme jen ty které máme v meta (chat modely, ne image/embedding)
            from app.services.llm.router import _xai_supports_reasoning_effort
            result = []
            for mid in live_ids:
                meta = _XAI_MODEL_META.get(mid)
                if not meta:
                    # Neznámý model — zařadíme jako advanced/basic podle názvu
                    meta = {
                        "label": mid,
                        "tier": "advanced",
                        "slow": "reasoning" in mid or "multi-agent" in mid,
                    }
                result.append(ModelPreset(
                    provider="xai", model=mid, label=meta["label"],
                    tier=meta["tier"], slow=meta["slow"], supports_search=True,
                    supports_reasoning_effort=_xai_supports_reasoning_effort(mid),
                ))
            # Seřaď: basic non-slow → basic slow → advanced
            result.sort(key=lambda m: (m.tier != "basic", m.slow, m.label))
            return result
    except Exception:
        # Fallback: vrať vše z metadata
        from app.services.llm.router import _xai_supports_reasoning_effort
        return [
            ModelPreset(
                provider="xai", model=mid, label=meta["label"],
                tier=meta["tier"], slow=meta["slow"], supports_search=True,
                supports_reasoning_effort=_xai_supports_reasoning_effort(mid),
            )
            for mid, meta in _XAI_MODEL_META.items()
        ]


@router.get("", response_model=ProvidersResponse)
async def get_providers(_: User = Depends(get_current_user)):
    """Vrátí dostupné providery včetně jejich modelů."""
    providers = []

    if settings.together_api_key:
        models = await get_together_models()
        if models:
            providers.append(ProviderInfo(id="together", available=True, models=models))

    if settings.openai_api_key:
        providers.append(ProviderInfo(id="openai", available=True, models=[
            ModelPreset(provider="openai", model="gpt-4o",      label="GPT-4o"),
            ModelPreset(provider="openai", model="gpt-4o-mini", label="GPT-4o mini"),
            ModelPreset(provider="openai", model="o3-mini",     label="o3 mini"),
        ]))

    if settings.anthropic_api_key:
        providers.append(ProviderInfo(id="anthropic", available=True, models=[
            ModelPreset(provider="anthropic", model="claude-opus-4-5",    label="Claude Opus 4.5"),
            ModelPreset(provider="anthropic", model="claude-sonnet-4-6",  label="Claude Sonnet 4.6"),
            ModelPreset(provider="anthropic", model="claude-sonnet-4-5",  label="Claude Sonnet 4.5"),
            ModelPreset(provider="anthropic", model="claude-haiku-3-5",   label="Claude Haiku 3.5"),
        ]))

    if settings.xai_api_key:
        xai_models = await get_xai_models()
        if xai_models:
            providers.append(ProviderInfo(id="xai", available=True, models=xai_models))

    ollama_models = await get_ollama_models()
    if ollama_models:
        providers.append(ProviderInfo(id="ollama", available=True, models=ollama_models))

    return ProvidersResponse(providers=providers)


@router.get("/preference", response_model=PreferenceResponse)
async def get_preference(current_user: User = Depends(get_current_user)):
    return PreferenceResponse(provider=current_user.preferred_provider, model=current_user.preferred_model)


@router.put("/preference", response_model=PreferenceResponse)
async def set_preference(
    body: PreferenceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.preferred_provider = body.provider
    current_user.preferred_model = body.model
    await db.commit()
    return PreferenceResponse(provider=current_user.preferred_provider, model=current_user.preferred_model)
