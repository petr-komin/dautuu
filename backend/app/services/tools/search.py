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


# ---------------------------------------------------------------------------
# Grok web search backend — zavolá xAI Live Search a vrátí výsledky ve stejném
# formátu jako Tavily, takže může sloužit jako drop-in náhrada pro non-xAI
# providery (Sonnet, GPT, Llama …).
# ---------------------------------------------------------------------------

async def grok_web_search(
    query: str,
    max_results: int = 8,
) -> tuple[list[SearchResult], SearchMeta]:
    """Zavolá Grok přes Responses API + Agent Tools (web_search) a vrátí
    výsledky + citations ve formátu Tavily.

    Po dubnu 2026 xAI deprecated `search_parameters` (Live Search v Chat
    Completions). Náhrada je `/v1/responses` endpoint s `tools=[{type:"web_search"}]`,
    který provede agentic web search server-side a vrátí annotations s URL
    citations. Voláme přes čistý httpx (OpenAI SDK 1.59 ještě nemá `responses`
    namespace).

    Args:
        query: Vyhledávací dotaz.
        max_results: Aproximativní limit citations (Responses API to nepřijímá
            přímo — slouží jen k truncate výsledku).

    Returns:
        (list výsledků, meta). Při chybě vrátí ([], meta success=False).
    """
    meta: SearchMeta = {
        "query": query,
        "provider": "grok",
        "search_depth": "agent_tools",
        "num_results": 0,
        "success": False,
    }

    if not settings.xai_api_key:
        log.warning("XAI_API_KEY není nastaven — Grok web search přeskočen")
        return [], meta

    try:
        import httpx

        headers = {
            "Authorization": f"Bearer {settings.xai_api_key}",
            "Content-Type": "application/json",
        }
        prompt = (
            f"Vyhledej na internetu aktuální informace k tomuto dotazu a stručně "
            f"je shrň v 4-7 větách. Uveď konkrétní fakta, čísla a data, ne obecné "
            f"fráze. Dotaz: {query}"
        )
        body = {
            "model": settings.grok_search_model,
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": settings.grok_search_max_tokens,
        }
        log.info("GROK_SEARCH query=%r model=%s max=%d",
                 query, settings.grok_search_model, max_results)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/responses",
                headers=headers,
                json=body,
            )
        if resp.status_code != 200:
            log.error("GROK_SEARCH_HTTP_%d body=%s", resp.status_code, resp.text[:300])
            return [], meta

        data = resp.json()

        # Vyparsuj output: text + annotations (url_citation)
        summary = ""
        annotations: list[dict] = []
        for item in data.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    summary += c.get("text", "")
                    for ann in c.get("annotations", []) or []:
                        if ann.get("type") == "url_citation" and ann.get("url"):
                            annotations.append(ann)

        # Sestav SearchResult-y. První result obsahuje LLM summary
        # (model už ho ukotvil k citations); ostatní jen URL+host.
        # Truncate na max_results.
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for i, ann in enumerate(annotations[:max_results]):
            url = ann["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                from urllib.parse import urlparse
                host = urlparse(url).hostname or url
            except Exception:
                host = url
            content = summary if not results else ""
            results.append(SearchResult(title=host, url=url, content=content))

        # Pokud Grok nevrátil žádné citace (jen sám odpověděl), vyrobíme jediný
        # "virtuální" výsledek se summary.
        if not results and summary:
            results.append(SearchResult(title="Grok summary", url="", content=summary))

        meta["num_results"] = len(results)
        meta["success"] = bool(results)
        log.info("GROK_SEARCH_DONE query=%r results=%d cits=%d",
                 query, len(results), len(annotations))
        return results, meta
    except Exception as exc:
        log.error("GROK_SEARCH_ERROR query=%r: %s: %s",
                  query, type(exc).__name__, exc)
        return [], meta
