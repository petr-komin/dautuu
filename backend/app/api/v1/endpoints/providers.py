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
            ModelPreset(provider="anthropic", model="claude-opus-4-5",   label="Claude Opus"),
            ModelPreset(provider="anthropic", model="claude-sonnet-4-5", label="Claude Sonnet"),
            ModelPreset(provider="anthropic", model="claude-haiku-3-5",  label="Claude Haiku"),
        ]))

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
