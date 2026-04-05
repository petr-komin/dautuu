"""Web search tool — Tavily AI Search.

Používá Tavily API pro vyhledávání aktuálních informací z internetu.
Vrací seznam výsledků s title, url a krátkým výtahem obsahu.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from app.core.config import settings

log = logging.getLogger("dautuu.tools.search")

# ---------------------------------------------------------------------------
# Definice tool pro LLM providery (OpenAI / Together / Ollama formát)
# ---------------------------------------------------------------------------

SEARCH_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Vyhledá aktuální informace na internetu. Použij tento nástroj, "
            "pokud otázka vyžaduje aktuální data, novinky, ceny, počasí, "
            "události nebo jiné informace, které se mění v čase nebo které "
            "nemusíš znát ze svého tréninku."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Vyhledávací dotaz v přirozeném jazyce.",
                }
            },
            "required": ["query"],
        },
    },
}

# Anthropic tool formát
SEARCH_TOOL_ANTHROPIC = {
    "name": "search_web",
    "description": (
        "Vyhledá aktuální informace na internetu. Použij tento nástroj, "
        "pokud otázka vyžaduje aktuální data, novinky, ceny, počasí, "
        "události nebo jiné informace, které se mění v čase nebo které "
        "nemusíš znát ze svého tréninku."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Vyhledávací dotaz v přirozeném jazyce.",
            }
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Výsledek hledání
# ---------------------------------------------------------------------------

class SearchResult(TypedDict):
    title: str
    url: str
    content: str


class SearchMeta(TypedDict):
    """Metadata o provedeném searchi — pro usage logging."""
    query: str
    provider: str
    search_depth: str
    num_results: int
    success: bool


# ---------------------------------------------------------------------------
# Hlavní funkce
# ---------------------------------------------------------------------------

async def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> tuple[list[SearchResult], SearchMeta]:
    """Vyhledá query přes Tavily a vrátí (výsledky, metadata).

    Args:
        query: Přirozený jazyk — dotaz co hledat.
        max_results: Maximální počet výsledků (default 5).
        search_depth: "basic" nebo "advanced" (ovlivňuje cenu).

    Returns:
        Tuple (list výsledků, SearchMeta pro usage logging).
        Při chybě vrátí ([], meta s success=False) — nepadá celý chat.
    """
    meta: SearchMeta = {
        "query": query,
        "provider": "tavily",
        "search_depth": search_depth,
        "num_results": 0,
        "success": False,
    }

    if not settings.tavily_api_key:
        log.warning("TAVILY_API_KEY není nastaven — web search přeskočen")
        return [], meta

    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=settings.tavily_api_key)
        log.info("WEB_SEARCH query=%r depth=%s", query, search_depth)
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=False,
        )
        results: list[SearchResult] = []
        for r in response.get("results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
            ))
        meta["num_results"] = len(results)
        meta["success"] = True
        log.info("WEB_SEARCH_DONE query=%r results=%d", query, len(results))
        return results, meta
    except Exception as exc:
        log.error("WEB_SEARCH_ERROR query=%r: %s: %s", query, type(exc).__name__, exc)
        return [], meta


def format_search_results(results: list[SearchResult]) -> str:
    """Formátuje výsledky hledání do čitelného textu pro LLM."""
    if not results:
        return "Vyhledávání nepřineslo žádné výsledky."
    lines = ["Výsledky vyhledávání na internetu:\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}")
        lines.append(f"    URL: {r['url']}")
        lines.append(f"    {r['content']}")
        lines.append("")
    return "\n".join(lines)
