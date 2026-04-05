"""MCP (Model Context Protocol) server endpoint.

Implementuje Streamable HTTP transport dle MCP spec 2025-03-26.
Nepouž­ívá mcp Python SDK — vše je implementováno nativně přes FastAPI.

Transport (Streamable HTTP — jedna URL pro vše):
  GET  /api/v1/mcp/{user_id}/sse  → SSE stream pro server-initiated zprávy (volitelné)
  POST /api/v1/mcp/{user_id}/sse  → přijme JSON-RPC, vrátí odpověď jako JSON
                                    (nebo SSE stream pokud klient chce streamovat)

Auth:
  Authorization: Bearer <api_key>   (UUID vygenerovaný přes POST /auth/api-key)

Exponované MCP tools:
  add_memory(text, category?)     → uloží vzpomínku do MCP Memory konverzace
  search_memory(query, limit?)    → sémantické vyhledávání přes pgvector
  list_memories(limit?)           → chronologický výpis vzpomínek
  delete_memory(memory_id)        → smaže konkrétní vzpomínku
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.db.session import get_db
from app.services.rag.embeddings import embed
from app.services.rag.memory import retrieve_memory

log = logging.getLogger("dautuu.mcp")

router = APIRouter(prefix="/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# MCP protocol constants
# ---------------------------------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "dautuu"
SERVER_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


async def _get_user_by_api_key(user_id: str, request: Request, db: AsyncSession):
    """Ověří Bearer token a vrátí User objekt."""
    from app.db.models import User

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chybí Authorization: Bearer <api_key> header",
        )
    raw_key = auth_header[len("Bearer "):].strip()

    try:
        key_uuid = uuid.UUID(raw_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Neplatný formát API klíče",
        )

    try:
        target_user_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Neplatný user_id v URL",
        )

    result = await db.execute(
        select(User).where(User.id == target_user_id, User.api_key == key_uuid)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Neplatný API klíč nebo user_id",
        )
    return user


# ---------------------------------------------------------------------------
# MCP Memory konverzace — lazy get-or-create
# ---------------------------------------------------------------------------


async def _get_or_create_mcp_conversation(user_id: uuid.UUID, db: AsyncSession) -> Conversation:
    """Vrátí existující MCP Memory konverzaci nebo ji vytvoří."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.is_mcp_memory == True,  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        user_id=user_id,
        title="MCP Memory",
        is_mcp_memory=True,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    log.info("MCP_CONV_CREATED user=%s conv=%s", user_id, conv.id)
    return conv


# ---------------------------------------------------------------------------
# MCP Tool implementations
# ---------------------------------------------------------------------------


async def tool_add_memory(
    user_id: uuid.UUID,
    text: str,
    category: str = "general",
    project: str | None = None,
    db: AsyncSession = None,
) -> dict:
    """Uloží vzpomínku do MCP Memory konverzace a zaindexuje ji."""
    conv = await _get_or_create_mcp_conversation(user_id, db)
    content = f"[{category}] {text}" if category and category != "general" else text

    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=content,
        model="mcp",
        mcp_project=project or None,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    try:
        msg.embedding = await embed(content)
        await db.commit()
        log.info("MCP_ADD_MEMORY msg=%s user=%s project=%s", msg.id, user_id, project)
    except Exception as exc:
        log.error("MCP_EMBED_ERROR msg=%s: %s", msg.id, exc)

    return {
        "memory_id": str(msg.id),
        "status": "saved",
        "category": category,
        "project": project,
        "preview": content[:100],
    }


async def tool_search_memory(
    user_id: uuid.UUID,
    query: str,
    limit: int = 5,
    project: str | None = None,
    db: AsyncSession = None,
) -> dict:
    """Sémanticky prohledá vzpomínky uživatele. Pokud je zadán project, hledá jen v něm."""
    conv = await _get_or_create_mcp_conversation(user_id, db)
    dummy_conv_id = uuid.uuid4()
    memory_text = await retrieve_memory(query=query, user_id=user_id, current_conv_id=dummy_conv_id, db=db)

    try:
        query_emb = await embed(query)
        base_filter = [
            Message.conversation_id == conv.id,
            Message.embedding.isnot(None),
        ]
        if project:
            base_filter.append(Message.mcp_project == project)

        similar = await db.execute(
            select(Message)
            .where(*base_filter)
            .order_by(Message.embedding.cosine_distance(query_emb))
            .limit(limit)
        )
        mcp_msgs = similar.scalars().all()
    except Exception as exc:
        log.error("MCP_SEARCH_ERROR: %s", exc)
        mcp_msgs = []

    return {
        "query": query,
        "project": project,
        "mcp_memories": [
            {
                "memory_id": str(m.id),
                "content": m.content,
                "project": m.mcp_project,
                "created_at": m.created_at.isoformat(),
            }
            for m in mcp_msgs
        ],
        "context": memory_text or "(žádné relevantní vzpomínky)",
    }


async def tool_list_memories(
    user_id: uuid.UUID,
    limit: int = 20,
    project: str | None = None,
    db: AsyncSession = None,
) -> dict:
    """Vrátí posledních N vzpomínek z MCP Memory konverzace. Pokud je zadán project, filtruje jen jeho vzpomínky."""
    conv = await _get_or_create_mcp_conversation(user_id, db)
    base_filter = [
        Message.conversation_id == conv.id,
        Message.role == "assistant",
    ]
    if project:
        base_filter.append(Message.mcp_project == project)

    result = await db.execute(
        select(Message)
        .where(*base_filter)
        .order_by(Message.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    messages = result.scalars().all()
    return {
        "total": len(messages),
        "project": project,
        "memories": [
            {
                "memory_id": str(m.id),
                "content": m.content,
                "project": m.mcp_project,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


async def tool_delete_memory(user_id: uuid.UUID, memory_id: str, db: AsyncSession = None) -> dict:
    """Smaže konkrétní vzpomínku (ověří vlastnictví)."""
    try:
        msg_uuid = uuid.UUID(memory_id)
    except ValueError:
        return {"error": f"Neplatný memory_id: {memory_id}"}

    conv = await _get_or_create_mcp_conversation(user_id, db)
    result = await db.execute(
        select(Message).where(Message.id == msg_uuid, Message.conversation_id == conv.id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        return {"error": f"Vzpomínka {memory_id} nebyla nalezena nebo nepatří tomuto uživateli"}

    await db.execute(delete(Message).where(Message.id == msg_uuid))
    await db.commit()
    log.info("MCP_DELETE_MEMORY msg=%s user=%s", msg_uuid, user_id)
    return {"status": "deleted", "memory_id": memory_id}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 dispatcher
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = [
    {
        "name": "add_memory",
        "description": (
            "Uloží textovou vzpomínku nebo informaci do dlouhodobé paměti. "
            "Použij pro zachování důležitých faktů, preferencí nebo kontextu mezi sezeními. "
            "Volitelně upřesni projekt (např. název repozitáře nebo workspace) pro pozdější filtrování."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text vzpomínky k uložení"},
                "category": {
                    "type": "string",
                    "description": "Kategorie vzpomínky (např. 'preference', 'fact', 'task'). Výchozí: 'general'",
                    "default": "general",
                },
                "project": {
                    "type": "string",
                    "description": "Název projektu nebo workspace (např. 'dautuu', 'muj-projekt'). Volitelné — pro filtrování vzpomínek dle projektu.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_memory",
        "description": (
            "Sémanticky prohledá dlouhodobou paměť a vrátí relevantní vzpomínky a kontext. "
            "Použij pro nalezení dříve uložených informací. "
            "Volitelně filtruj jen vzpomínky z konkrétního projektu."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Dotaz pro vyhledávání"},
                "limit": {"type": "integer", "description": "Maximální počet výsledků (výchozí: 5, max: 20)", "default": 5},
                "project": {
                    "type": "string",
                    "description": "Filtrovat jen vzpomínky z tohoto projektu. Pokud není zadán, hledá napříč všemi projekty.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_memories",
        "description": (
            "Vrátí chronologický seznam posledních vzpomínek uložených přes MCP. "
            "Volitelně filtruj jen vzpomínky z konkrétního projektu."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximální počet vzpomínek (výchozí: 20, max: 100)", "default": 20},
                "project": {
                    "type": "string",
                    "description": "Filtrovat jen vzpomínky z tohoto projektu. Pokud není zadán, vrátí vzpomínky ze všech projektů.",
                },
            },
        },
    },
    {
        "name": "delete_memory",
        "description": "Smaže konkrétní vzpomínku podle jejího ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "UUID vzpomínky k smazání"},
            },
            "required": ["memory_id"],
        },
    },
]


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _dispatch(message: dict, user_id: uuid.UUID, db: AsyncSession) -> dict | None:
    """Zpracuje jeden JSON-RPC 2.0 požadavek a vrátí odpověď (nebo None pro notifications)."""
    method = message.get("method", "")
    params = message.get("params", {}) or {}
    req_id = message.get("id")

    log.info("MCP_DISPATCH method=%s user=%s id=%s", method, user_id, req_id)

    # ---- Lifecycle ----
    if method == "initialize":
        return _jsonrpc_result(req_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # notification → no response

    if method == "ping":
        return _jsonrpc_result(req_id, {})

    # ---- Tools ----
    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": TOOLS_SCHEMA})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {}) or {}

        try:
            if tool_name == "add_memory":
                result = await tool_add_memory(
                    user_id=user_id,
                    text=arguments.get("text", ""),
                    category=arguments.get("category", "general"),
                    project=arguments.get("project") or None,
                    db=db,
                )
            elif tool_name == "search_memory":
                result = await tool_search_memory(
                    user_id=user_id,
                    query=arguments.get("query", ""),
                    limit=int(arguments.get("limit", 5)),
                    project=arguments.get("project") or None,
                    db=db,
                )
            elif tool_name == "list_memories":
                result = await tool_list_memories(
                    user_id=user_id,
                    limit=int(arguments.get("limit", 20)),
                    project=arguments.get("project") or None,
                    db=db,
                )
            elif tool_name == "delete_memory":
                result = await tool_delete_memory(
                    user_id=user_id,
                    memory_id=arguments.get("memory_id", ""),
                    db=db,
                )
            else:
                return _jsonrpc_error(req_id, -32601, f"Neznámý tool: {tool_name}")

            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "isError": "error" in result,
            })

        except Exception as exc:
            log.exception("MCP_TOOL_ERROR tool=%s user=%s", tool_name, user_id)
            return _jsonrpc_error(req_id, -32603, f"Chyba při volání tool {tool_name}: {exc}")

    # ---- Unknown method ----
    if req_id is not None:
        return _jsonrpc_error(req_id, -32601, f"Neznámá metoda: {method}")

    return None  # unknown notification → ignore


# ---------------------------------------------------------------------------
# Streamable HTTP transport — jedna URL, POST vrací JSON přímo
# ---------------------------------------------------------------------------


@router.post("/{user_id}/sse")
async def mcp_post(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Streamable HTTP POST — přijme JSON-RPC zprávu, vrátí odpověď jako JSON.

    OpenCode a většina moderních MCP klientů posílá POST přímo na SSE URL.
    Odpověď je synchronní JSON (ne SSE stream) — to Streamable HTTP transport umožňuje.
    """
    user = await _get_user_by_api_key(user_id, request, db)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Neplatný JSON")

    # Batch nebo single request
    if isinstance(body, list):
        responses = []
        for msg in body:
            resp = await _dispatch(msg, user.id, db)
            if resp is not None:
                responses.append(resp)
        # Batch: vrátíme pole (nebo 202 pokud jen notifikace)
        if not responses:
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=responses)
    else:
        resp = await _dispatch(body, user.id, db)
        if resp is None:
            # Notifikace — žádná odpověď
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=resp)


@router.get("/{user_id}/sse")
async def mcp_get(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GET na SSE URL — vrátí 405 s vysvětlením.

    Streamable HTTP transport nepotřebuje persistentní SSE stream od serveru.
    Klient posílá POST a dostane synchronní JSON odpověď.
    Tento endpoint existuje jen pro případ že klient zkouší GET (starý SSE transport).
    """
    await _get_user_by_api_key(user_id, request, db)
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=(
            "Dautuu MCP používá Streamable HTTP transport — posílej POST na tuto URL. "
            "GET (persistentní SSE stream) není podporován."
        ),
    )
