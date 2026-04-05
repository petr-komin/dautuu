"""CRUD endpointy pro správu externích MCP serverů uživatele."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import McpServer, User
from app.db.session import get_db
from app.services.mcp_client import fetch_server_tools

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


# ---------------------------------------------------------------------------
# Pydantic schémata
# ---------------------------------------------------------------------------

class McpServerCreate(BaseModel):
    name: str
    url: str
    headers: dict[str, str] = {}
    enabled: bool = True
    transport_type: str = "streamable_http"  # streamable_http | sse


class McpServerUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None
    transport_type: str | None = None


class McpServerOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    headers: dict[str, Any]
    enabled: bool
    transport_type: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_server_or_404(server_id: uuid.UUID, user: User, db: AsyncSession) -> McpServer:
    result = await db.execute(
        select(McpServer).where(McpServer.id == server_id, McpServer.user_id == user.id)
    )
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server nenalezen")
    return server


# ---------------------------------------------------------------------------
# Endpointy
# ---------------------------------------------------------------------------

@router.get("", response_model=list[McpServerOut])
async def list_mcp_servers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Vrátí seznam všech MCP serverů uživatele."""
    result = await db.execute(
        select(McpServer)
        .where(McpServer.user_id == user.id)
        .order_by(McpServer.created_at)
    )
    return result.scalars().all()


@router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: McpServerCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Přidá nový MCP server."""
    server = McpServer(
        user_id=user.id,
        name=body.name,
        url=body.url,
        headers=body.headers,
        enabled=body.enabled,
        transport_type=body.transport_type,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


@router.patch("/{server_id}", response_model=McpServerOut)
async def update_mcp_server(
    server_id: uuid.UUID,
    body: McpServerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upraví existující MCP server (částečný update)."""
    server = await _get_server_or_404(server_id, user, db)
    if body.name is not None:
        server.name = body.name
    if body.url is not None:
        server.url = body.url
    if body.headers is not None:
        server.headers = body.headers
    if body.enabled is not None:
        server.enabled = body.enabled
    if body.transport_type is not None:
        server.transport_type = body.transport_type
    await db.commit()
    await db.refresh(server)
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Smaže MCP server."""
    server = await _get_server_or_404(server_id, user, db)
    await db.delete(server)
    await db.commit()


@router.post("/{server_id}/test")
async def test_mcp_server(
    server_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Otestuje připojení k MCP serveru — zavolá tools/list a vrátí seznam tools."""
    server = await _get_server_or_404(server_id, user, db)
    tools = await fetch_server_tools(server)
    return {
        "ok": True,
        "tools_count": len(tools),
        "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools],
    }
