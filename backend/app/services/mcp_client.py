"""MCP klient — dautuu jako klient externích MCP serverů.

Podporuje dva HTTP transporty:
- streamable_http: POST přímo na URL, synchronní JSON odpověď (nebo SSE stream)
- sse: GET na URL → SSE stream → endpoint event → POST na session URL → SSE odpověď

Každý tool ze vzdáleného serveru dostane prefix {server_name}__{tool_name} aby
nedošlo ke kolizi názvů mezi servery a interními tools.

Použití v chat.py:
    from app.services.mcp_client import get_user_mcp_tools, call_mcp_tool

    # Při sestavování tools listu pro LLM:
    tools += await get_user_mcp_tools(user_id, db, provider)

    # Při dispatchi tool callu:
    result = await call_mcp_tool(tool_name, args, user_id, db)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import McpServer

log = logging.getLogger("dautuu.mcp_client")

# Timeout pro volání externích MCP serverů
MCP_TIMEOUT = 15.0

# Oddělovač mezi názvem serveru a názvem toolu
TOOL_PREFIX_SEP = "__"


def _server_prefix(server_name: str) -> str:
    """Normalizuje název serveru na bezpečný prefix (jen [a-z0-9_])."""
    return "".join(c if c.isalnum() else "_" for c in server_name.lower())


def _tool_name(server_name: str, tool_name: str) -> str:
    return f"{_server_prefix(server_name)}{TOOL_PREFIX_SEP}{tool_name}"


def parse_server_from_tool_name(prefixed_name: str) -> tuple[str, str] | None:
    """Vrátí (server_prefix, original_tool_name) nebo None pokud to není prefixovaný tool."""
    if TOOL_PREFIX_SEP not in prefixed_name:
        return None
    prefix, _, original = prefixed_name.partition(TOOL_PREFIX_SEP)
    return prefix, original


# ---------------------------------------------------------------------------
# Nízkoúrovňové MCP volání — Streamable HTTP transport
# ---------------------------------------------------------------------------

async def _mcp_request_streamable_http(
    url: str, headers: dict, method: str, params: dict | None = None
) -> Any:
    """Pošle JSON-RPC 2.0 request přes Streamable HTTP transport a vrátí result."""
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
    }
    if params:
        payload["params"] = params

    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **headers,
    }

    async with httpx.AsyncClient(timeout=MCP_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=req_headers)
        resp.raise_for_status()

    # Odpověď může být plain JSON nebo SSE — vždy vezmeme první JSON objekt
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        # Parsuj SSE a najdi první "data:" řádek s JSON
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str:
                    data = json.loads(data_str)
                    if "error" in data:
                        raise RuntimeError(f"MCP chyba: {data['error']}")
                    return data.get("result")
        return None
    else:
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP chyba: {data['error']}")
        return data.get("result")


# ---------------------------------------------------------------------------
# Nízkoúrovňové MCP volání — SSE transport
# ---------------------------------------------------------------------------

async def _mcp_request_sse(
    url: str, headers: dict, method: str, params: dict | None = None
) -> Any:
    """Pošle JSON-RPC 2.0 request přes SSE transport a vrátí result.

    SSE MCP handshake v rámci jednoho spojení:
    1. GET {url} → SSE stream, čekáme na 'endpoint' event se session URL
    2. POST initialize → čekáme na 'message' s výsledkem
    3. POST notifications/initialized (bez čekání na odpověď)
    4. POST {method} → čekáme na 'message' s výsledkem
    """
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    post_headers = {"Content-Type": "application/json", **headers}

    def _build_payload(m: str, p: dict | None = None) -> dict:
        pl: dict[str, Any] = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": m}
        if p:
            pl["params"] = p
        return pl

    init_payload = _build_payload("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "dautuu", "version": "0.1.0"},
    })
    init_id = init_payload["id"]

    main_payload = _build_payload(method, params)
    main_id = main_payload["id"]

    async with httpx.AsyncClient(timeout=MCP_TIMEOUT) as client:
        async with client.stream("GET", url, headers={"Accept": "text/event-stream", **headers}) as sse_resp:
            sse_resp.raise_for_status()

            session_url: str | None = None
            initialized = False
            result_data: Any = None
            current_event: str | None = None

            async for line in sse_resp.aiter_lines():
                line = line.rstrip()

                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()

                elif line.startswith("data:"):
                    data_str = line[len("data:"):].strip()

                    if current_event == "endpoint":
                        # Získáme session URL a zahájíme initialize
                        session_url = data_str if data_str.startswith("http") else base_url + data_str
                        await client.post(session_url, json=init_payload, headers=post_headers)

                    elif current_event == "message" and session_url and data_str:
                        data = json.loads(data_str)
                        msg_id = data.get("id")

                        if msg_id == init_id:
                            # Initialize hotovo — pošleme initialized notification (bez id = notification)
                            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                            await client.post(session_url, json=notif, headers=post_headers)
                            # Pošleme skutečný request
                            await client.post(session_url, json=main_payload, headers=post_headers)
                            initialized = True

                        elif msg_id == main_id and initialized:
                            # Odpověď na náš hlavní request
                            if "error" in data:
                                raise RuntimeError(f"MCP chyba: {data['error']}")
                            result_data = data.get("result")
                            break

                elif line == "":
                    current_event = None

            return result_data


# ---------------------------------------------------------------------------
# Dispatcher — vybere transport podle server.transport_type
# ---------------------------------------------------------------------------

async def _mcp_request(server: McpServer, method: str, params: dict | None = None) -> Any:
    """Dispatcher: vybere správný transport podle server.transport_type."""
    transport = getattr(server, "transport_type", "streamable_http")
    if transport == "sse":
        return await _mcp_request_sse(server.url, server.headers or {}, method, params)
    else:
        return await _mcp_request_streamable_http(server.url, server.headers or {}, method, params)


# ---------------------------------------------------------------------------
# Veřejné API
# ---------------------------------------------------------------------------

async def fetch_server_tools(server: McpServer) -> list[dict]:
    """Zavolá tools/list na MCP server. Vrátí seznam tool definic nebo [] při chybě."""
    try:
        transport = getattr(server, "transport_type", "streamable_http")

        # Streamable HTTP: posíláme initialize před každým voláním (stateless přístup)
        # SSE: initialize je součástí _mcp_request_sse — nepotřebujeme volat zvlášť
        if transport != "sse":
            await _mcp_request(server, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dautuu", "version": "0.1.0"},
            })

        result = await _mcp_request(server, "tools/list")
        return result.get("tools", []) if result else []
    except Exception as exc:
        log.warning(
            "MCP_CLIENT tools/list failed server=%s url=%s transport=%s: %s",
            server.name, server.url, getattr(server, "transport_type", "?"), exc,
        )
        return []


async def call_server_tool(server: McpServer, tool_name: str, arguments: dict) -> str:
    """Zavolá tools/call na MCP server. Vrátí textový výsledek nebo chybovou zprávu."""
    try:
        transport = getattr(server, "transport_type", "streamable_http")

        # Streamable HTTP: initialize před každým voláním
        # SSE: initialize je součástí _mcp_request_sse
        if transport != "sse":
            await _mcp_request(server, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dautuu", "version": "0.1.0"},
            })

        result = await _mcp_request(server, "tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if not result:
            return "(prázdná odpověď)"
        # Standardní MCP odpověď: {"content": [{"type": "text", "text": "..."}]}
        content = result.get("content", [])
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        log.error(
            "MCP_CLIENT tools/call failed server=%s tool=%s transport=%s: %s",
            server.name, tool_name, getattr(server, "transport_type", "?"), exc,
        )
        return f"[Chyba při volání {server.name}/{tool_name}: {exc}]"


# ---------------------------------------------------------------------------
# Integrace s chat.py
# ---------------------------------------------------------------------------

async def get_user_mcp_tools(user_id: uuid.UUID, db: AsyncSession, provider: str) -> list[dict]:
    """Načte tools ze všech enabled MCP serverů uživatele, přidá prefix k názvům.

    Vrátí tools ve správném formátu pro daného providera (OpenAI vs Anthropic).
    """
    result = await db.execute(
        select(McpServer).where(
            McpServer.user_id == user_id,
            McpServer.enabled == True,  # noqa: E712
        )
    )
    servers = result.scalars().all()
    if not servers:
        return []

    is_anthropic = provider == "anthropic"
    all_tools: list[dict] = []

    for server in servers:
        raw_tools = await fetch_server_tools(server)
        prefix = _server_prefix(server.name)

        for tool in raw_tools:
            original_name = tool.get("name", "")
            prefixed_name = f"{prefix}{TOOL_PREFIX_SEP}{original_name}"
            description = f"[{server.name}] {tool.get('description', '')}"
            schema = tool.get("inputSchema") or tool.get("parameters") or {"type": "object", "properties": {}}

            if is_anthropic:
                all_tools.append({
                    "name": prefixed_name,
                    "description": description,
                    "input_schema": schema,
                })
            else:
                all_tools.append({
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": description,
                        "parameters": schema,
                    },
                })

    log.info("MCP_CLIENT loaded %d tools from %d servers for user=%s", len(all_tools), len(servers), user_id)
    return all_tools


async def call_mcp_tool(prefixed_tool_name: str, arguments: dict, user_id: uuid.UUID, db: AsyncSession) -> str:
    """Najde správný MCP server podle prefixu a zavolá tool. Vrátí textový výsledek."""
    parsed = parse_server_from_tool_name(prefixed_tool_name)
    if not parsed:
        return f"[Interní chyba: {prefixed_tool_name} není MCP tool]"

    server_prefix, original_tool_name = parsed

    result = await db.execute(
        select(McpServer).where(
            McpServer.user_id == user_id,
            McpServer.enabled == True,  # noqa: E712
        )
    )
    servers = result.scalars().all()

    for server in servers:
        if _server_prefix(server.name) == server_prefix:
            return await call_server_tool(server, original_tool_name, arguments)

    return f"[MCP server pro prefix '{server_prefix}' nenalezen nebo je vypnutý]"
