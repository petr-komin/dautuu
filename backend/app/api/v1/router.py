from fastapi import APIRouter

from app.api.v1.endpoints import auth, chat, providers, usage

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(providers.router)
api_router.include_router(usage.router)
