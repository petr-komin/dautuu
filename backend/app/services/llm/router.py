"""LLM Router — jednotné rozhraní pro různé providery.

Podporované providery:
  - together   (primární)
  - openai
  - anthropic
  - ollama
  - xai        (Grok modely, OpenAI-kompatibilní API, volitelný Live Search)
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings

log = logging.getLogger("dautuu.llm.router")

Provider = Literal["together", "openai", "anthropic", "ollama", "xai"]


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str
    # Pokud je nastaven, použije se místo automaticky generovaného {"role": ..., "content": ...}
    # Slouží pro tool_call a tool_result zprávy kde formát závisí na provideru a nelze
    # jej genericky vyjádřit přes role+content.
    # Ignorováno pro Anthropic (ten má vlastní konverzi v _split_system).
    _raw_openai: dict | None = field(default=None, repr=False)
    _raw_anthropic: dict | None = field(default=None, repr=False)


@dataclass
class UsageInfo:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    # Live Search metadata (xAI / Grok)
    citations: list[str] = field(default_factory=list)
    num_sources_used: int = 0


@dataclass
class ChatResponse:
    content: str
    model: str
    provider: Provider
    usage: UsageInfo = field(default_factory=UsageInfo)


@dataclass
class XaiSearchOptions:
    """Konfigurace xAI Live Search (search_parameters podle docs.x.ai)."""
    enabled: bool = False
    mode: Literal["off", "on", "auto"] = "auto"
    return_citations: bool = True
    max_search_results: int = 15
    sources: list[dict] | None = None     # [{"type": "web"}, {"type": "x"}, {"type": "news"}]
    from_date: str | None = None          # ISO YYYY-MM-DD
    to_date: str | None = None
    allowed_domains: list[str] | None = None   # max 5
    excluded_domains: list[str] | None = None  # max 5

    def to_params(self) -> dict | None:
        if not self.enabled or self.mode == "off":
            return None
        params: dict = {
            "mode": self.mode,
            "return_citations": self.return_citations,
            "max_search_results": self.max_search_results,
        }
        srcs = self.sources or [{"type": "web"}, {"type": "x"}, {"type": "news"}]
        # allowed/excluded domains se aplikují na web zdroj
        if self.allowed_domains or self.excluded_domains:
            srcs = []
            for s in (self.sources or [{"type": "web"}, {"type": "x"}, {"type": "news"}]):
                if s.get("type") == "web":
                    s = dict(s)
                    if self.allowed_domains:
                        s["allowed_websites"] = self.allowed_domains[:5]
                    elif self.excluded_domains:
                        s["excluded_websites"] = self.excluded_domains[:5]
                srcs.append(s)
        params["sources"] = srcs
        if self.from_date:
            params["from_date"] = self.from_date
        if self.to_date:
            params["to_date"] = self.to_date
        return params


@dataclass
class XaiOptions:
    """Volitelné xAI-specific parametry."""
    search: XaiSearchOptions = field(default_factory=XaiSearchOptions)
    reasoning_effort: Literal["low", "high"] | None = None  # jen pro reasoning modely (kromě grok-4)


@dataclass
class ToolCall:
    """Jeden tool call požadovaný LLM."""
    name: str
    args: dict
    tool_call_id: str = ""   # ID přiřazené modelem (OpenAI/Together: tc.id, Anthropic: block.id)


@dataclass
class ToolCallResult:
    """Výsledek LLM volání s tool callingem."""
    tool_calls: list[ToolCall]     # prázdné = LLM odpověděl přímo
    direct_content: str | None     # vyplněno pokud LLM odpověděl rovnou (žádné tool calls)
    usage: UsageInfo = field(default_factory=UsageInfo)

    # Zpětná kompatibilita — první tool call (nebo None)
    @property
    def tool_name(self) -> str | None:
        return self.tool_calls[0].name if self.tool_calls else None

    @property
    def tool_args(self) -> dict | None:
        return self.tool_calls[0].args if self.tool_calls else None


async def chat(
    messages: list[ChatMessage],
    model: str,
    provider: Provider = "together",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    search: bool = False,
    xai: XaiOptions | None = None,
) -> ChatResponse:
    """Pošle zprávy zvolenému LLM a vrátí odpověď.

    Pro xAI provider lze předat `xai=XaiOptions(...)` pro Live Search a reasoning_effort.
    Backwards-compat: `search=True` zapne default Live Search (mode=auto, web+x+news).
    """
    if provider == "together":
        return await _together_chat(messages, model, temperature, max_tokens)
    if provider == "openai":
        return await _openai_chat(messages, model, temperature, max_tokens)
    if provider == "anthropic":
        return await _anthropic_chat(messages, model, temperature, max_tokens)
    if provider == "ollama":
        return await _ollama_chat(messages, model, temperature, max_tokens)
    if provider == "xai":
        return await _xai_chat(messages, model, temperature, max_tokens,
                               xai=_resolve_xai(xai, search))
    raise ValueError(f"Neznámý provider: {provider}")


def _resolve_xai(xai: XaiOptions | None, search_legacy: bool) -> XaiOptions:
    """Sjednotí staré `search: bool` API s novým `xai: XaiOptions`."""
    if xai is not None:
        return xai
    return XaiOptions(search=XaiSearchOptions(enabled=search_legacy))


async def chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    provider: Provider = "together",
    tools: list[dict] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 512,
    search: bool = False,
    xai: XaiOptions | None = None,
) -> ToolCallResult:
    """LLM volání s tool definicemi — zjistí zda LLM chce volat tool(y).

    Vrátí ToolCallResult:
    - Pokud LLM chce zavolat tool(y): tool_calls je neprázdné
    - Pokud LLM odpověděl přímo: direct_content je vyplněn, tool_calls je []
    """
    if not tools:
        resp = await chat(messages, model, provider, temperature, max_tokens,
                          search=search, xai=xai)
        return ToolCallResult(
            tool_calls=[],
            direct_content=resp.content,
            usage=resp.usage,
        )

    if provider == "openai":
        return await _openai_chat_with_tools(messages, model, tools, temperature, max_tokens)
    if provider == "anthropic":
        return await _anthropic_chat_with_tools(messages, model, tools, temperature, max_tokens)
    if provider == "together":
        return await _together_chat_with_tools(messages, model, tools, temperature, max_tokens)
    if provider == "ollama":
        return await _ollama_chat_with_tools(messages, model, tools, temperature, max_tokens)
    if provider == "xai":
        return await _xai_chat_with_tools(messages, model, tools, temperature, max_tokens,
                                          xai=_resolve_xai(xai, search))
    raise ValueError(f"Neznámý provider: {provider}")


async def stream(
    messages: list[ChatMessage],
    model: str,
    provider: Provider = "together",
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """Streamuje tokeny ze zvoleného LLM (bez usage info)."""
    async for chunk, _ in stream_with_usage(messages, model, provider, temperature, max_tokens):
        yield chunk


async def stream_with_usage(
    messages: list[ChatMessage],
    model: str,
    provider: Provider = "together",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    search: bool = False,
    xai: XaiOptions | None = None,
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    """Streamuje tokeny ze zvoleného LLM.

    Yields: (chunk_text, None) pro každý token; pak ("" , UsageInfo) jako poslední yield
    s vyplněným usage po skončení streamu.
    """
    if provider == "together":
        async for item in _together_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    elif provider == "openai":
        async for item in _openai_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    elif provider == "anthropic":
        async for item in _anthropic_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    elif provider == "ollama":
        async for item in _ollama_stream_with_usage(messages, model, temperature, max_tokens):
            yield item
    elif provider == "xai":
        async for item in _xai_stream_with_usage(messages, model, temperature, max_tokens,
                                                 xai=_resolve_xai(xai, search)):
            yield item
    else:
        raise ValueError(f"Neznámý provider: {provider}")


# ---------------------------------------------------------------------------
# Together.ai
# ---------------------------------------------------------------------------

def _together_messages(messages: list[ChatMessage]) -> list[dict]:
    result = []
    for m in messages:
        if m._raw_openai is not None:
            result.append(m._raw_openai)
        else:
            result.append({"role": m.role, "content": m.content})
    return result


async def _together_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    from together import AsyncTogether

    client = AsyncTogether(api_key=settings.together_api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=_together_messages(messages),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or ""
    usage = UsageInfo(
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
    )
    return ChatResponse(content=content, model=model, provider="together", usage=usage)


async def _together_chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict],
    temperature: float,
    max_tokens: int,
) -> ToolCallResult:
    """Together tool calling — používá OpenAI-kompatibilní formát."""
    from together import AsyncTogether

    client = AsyncTogether(api_key=settings.together_api_key)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=_together_messages(messages),
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = UsageInfo(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )
        choice = resp.choices[0]
        # Některé modely (DeepSeek, starší Llama) vrátí tool_calls ale s finish_reason="stop"
        # Proto kontrolujeme přítomnost tool_calls v message, ne jen finish_reason
        if choice.message.tool_calls:
            calls = []
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                calls.append(ToolCall(name=tc.function.name, args=args, tool_call_id=tc.id or ""))
            log.debug("TOGETHER_TOOL_CALLS finish_reason=%r calls=%d", choice.finish_reason, len(calls))
            return ToolCallResult(tool_calls=calls, direct_content=None, usage=usage)
        log.debug("TOGETHER_DIRECT finish_reason=%r content_len=%d", choice.finish_reason, len(choice.message.content or ""))
        return ToolCallResult(
            tool_calls=[],
            direct_content=choice.message.content or "",
            usage=usage,
        )
    except Exception as exc:
        log.warning("TOGETHER_TOOL_CALL_FAILED %s: %s — fallback bez toolů", type(exc).__name__, exc)
        resp = await _together_chat(messages, model, temperature, max_tokens)
        return ToolCallResult(tool_calls=[], direct_content=resp.content, usage=resp.usage)


async def _together_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    from together import AsyncTogether

    client = AsyncTogether(api_key=settings.together_api_key)
    usage = UsageInfo()
    async for chunk in await client.chat.completions.create(
        model=model,
        messages=_together_messages(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    ):
        # Poslední chunk od Together: choices=[] a usage je vyplněné
        if not chunk.choices:
            if chunk.usage:
                usage.input_tokens = chunk.usage.prompt_tokens or 0
                usage.output_tokens = chunk.usage.completion_tokens or 0
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield (delta, None)
    yield ("", usage)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _openai_messages(messages: list[ChatMessage]) -> list[dict]:
    result = []
    for m in messages:
        if m._raw_openai is not None:
            result.append(m._raw_openai)
        else:
            result.append({"role": m.role, "content": m.content})
    return result


async def _openai_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=_openai_messages(messages),  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or ""
    usage = UsageInfo(
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
    )
    return ChatResponse(content=content, model=model, provider="openai", usage=usage)


async def _openai_chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict],
    temperature: float,
    max_tokens: int,
) -> ToolCallResult:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=_openai_messages(messages),  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    usage = UsageInfo(
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
    )
    choice = resp.choices[0]
    if choice.message.tool_calls:
        calls = []
        for tc in choice.message.tool_calls:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            calls.append(ToolCall(name=tc.function.name, args=args, tool_call_id=tc.id or ""))
        return ToolCallResult(tool_calls=calls, direct_content=None, usage=usage)
    return ToolCallResult(
        tool_calls=[],
        direct_content=choice.message.content or "",
        usage=usage,
    )


async def _openai_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    usage = UsageInfo()
    s = await client.chat.completions.create(
        model=model,
        messages=_openai_messages(messages),  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in s:
        # Poslední chunk od OpenAI s include_usage: choices=[] a usage je vyplněné
        if not chunk.choices:
            if chunk.usage:
                usage.input_tokens = chunk.usage.prompt_tokens or 0
                usage.output_tokens = chunk.usage.completion_tokens or 0
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield (delta, None)
    yield ("", usage)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def _split_system(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    """Anthropic přijímá system prompt zvlášť. Vrátí (system_text, messages_as_dicts)."""
    system = ""
    rest: list[dict] = []
    for m in messages:
        if m.role == "system":
            system += m.content + "\n"
        elif m._raw_anthropic is not None:
            rest.append(m._raw_anthropic)
        else:
            rest.append({"role": m.role, "content": m.content})
    # Debug: shrnutí struktury tool_use / tool_result pairs
    try:
        import logging as _logging
        _log = _logging.getLogger("dautuu.router.anthropic")
        if _log.isEnabledFor(_logging.DEBUG) or any(
            isinstance(m.get("content"), list) and m["content"]
            and isinstance(m["content"][0], dict)
            and m["content"][0].get("type") in ("tool_use", "tool_result")
            for m in rest
        ):
            summary = []
            for i, m in enumerate(rest):
                c = m.get("content")
                if isinstance(c, list):
                    types = [b.get("type", "?") if isinstance(b, dict) else "txt" for b in c]
                    ids = [
                        (b.get("id") or b.get("tool_use_id") or "")[:14]
                        if isinstance(b, dict) else ""
                        for b in c
                    ]
                    summary.append(f"  [{i}] {m.get('role')}: {types} ids={ids}")
                else:
                    txt = (c or "")[:30].replace("\n", " ")
                    summary.append(f"  [{i}] {m.get('role')}: text={txt!r}")
            _log.warning("ANTHROPIC_MSG_STRUCT (%d msgs):\n%s", len(rest), "\n".join(summary))
    except Exception:
        pass
    return system.strip(), rest


async def _anthropic_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, rest = _split_system(messages)
    kwargs: dict = dict(
        model=model,
        messages=rest,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    content = resp.content[0].text if resp.content else ""
    usage = UsageInfo(
        input_tokens=resp.usage.input_tokens if resp.usage else 0,
        output_tokens=resp.usage.output_tokens if resp.usage else 0,
    )
    return ChatResponse(content=content, model=model, provider="anthropic", usage=usage)


async def _anthropic_chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict],
    temperature: float,
    max_tokens: int,
) -> ToolCallResult:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, rest = _split_system(messages)
    kwargs: dict = dict(
        model=model,
        messages=rest,
        tools=tools,  # type: ignore[arg-type]
        tool_choice={"type": "auto"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    usage = UsageInfo(
        input_tokens=resp.usage.input_tokens if resp.usage else 0,
        output_tokens=resp.usage.output_tokens if resp.usage else 0,
    )
    calls = []
    text_parts = []
    for block in resp.content:
        if block.type == "tool_use":
            calls.append(ToolCall(
                name=block.name,
                args=block.input if isinstance(block.input, dict) else {},
                tool_call_id=block.id or "",
            ))
        elif hasattr(block, "text"):
            text_parts.append(block.text)
    if calls:
        return ToolCallResult(tool_calls=calls, direct_content=None, usage=usage)
    return ToolCallResult(
        tool_calls=[],
        direct_content="".join(text_parts),
        usage=usage,
    )


async def _anthropic_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, rest = _split_system(messages)
    kwargs: dict = dict(
        model=model,
        messages=rest,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if system:
        kwargs["system"] = system

    usage = UsageInfo()
    async with client.messages.stream(**kwargs) as s:
        async for text in s.text_stream:
            yield (text, None)
        # Po skončení streamu získáme finální zprávu s usage
        final = await s.get_final_message()
        if final.usage:
            usage.input_tokens = final.usage.input_tokens
            usage.output_tokens = final.usage.output_tokens
    yield ("", usage)


# ---------------------------------------------------------------------------
# Ollama (lokální)
# ---------------------------------------------------------------------------

async def _ollama_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    import httpx

    payload = {
        "model": model,
        "messages": _together_messages(messages),
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120) as client:
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["message"]["content"]
        usage = UsageInfo(
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
    return ChatResponse(content=content, model=model, provider="ollama", usage=usage)


async def _ollama_chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict],
    temperature: float,
    max_tokens: int,
) -> ToolCallResult:
    import httpx

    payload = {
        "model": model,
        "messages": _together_messages(messages),
        "tools": tools,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120) as client:
            resp = await client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})
            tool_calls_raw = msg.get("tool_calls", [])
            usage = UsageInfo(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            )
            if tool_calls_raw:
                calls = []
                for tc in tool_calls_raw:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    calls.append(ToolCall(name=fn.get("name", ""), args=args, tool_call_id=""))
                return ToolCallResult(tool_calls=calls, direct_content=None, usage=usage)
            return ToolCallResult(
                tool_calls=[],
                direct_content=msg.get("content", ""),
                usage=usage,
            )
    except Exception as exc:
        log.warning("OLLAMA_TOOL_CALL_FAILED %s: %s — fallback bez toolů", type(exc).__name__, exc)
        resp_obj = await _ollama_chat(messages, model, temperature, max_tokens)
        return ToolCallResult(tool_calls=[], direct_content=resp_obj.content, usage=resp_obj.usage)


async def _ollama_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    import httpx

    payload = {
        "model": model,
        "messages": _together_messages(messages),
        "stream": True,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    usage = UsageInfo()
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120) as client:
        async with client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield (chunk, None)
                    # Poslední chunk: done=true, obsahuje akumulované tokeny
                    if data.get("done"):
                        usage.input_tokens = data.get("prompt_eval_count", 0)
                        usage.output_tokens = data.get("eval_count", 0)
    yield ("", usage)


# ---------------------------------------------------------------------------
# xAI / Grok (OpenAI-kompatibilní API na https://api.x.ai/v1)
#
# Klíčové odlišnosti od OpenAI:
#   - Endpoint je `/v1/responses` (Responses API), NE `/v1/chat/completions`.
#     Chat Completions je sice taky podporován, ale `search_parameters` (Live Search)
#     na něm vrací 410 Gone — xAI je zmigrovala na Agent Tools v Responses API.
#   - Web search se zapíná jako server-side tool: `tools: [{"type": "web_search"}]`
#     (NE přes search_parameters).
#   - Reasoning modely (kromě grok-4) podporují `reasoning.effort: low|medium|high`.
#   - Response má `output[]` s heterogenními items: message, function_call,
#     web_search_call, reasoning. Citations jsou v `message.content[].annotations`
#     jako `url_citation`.
#   - Function tools mají FLAT formát `{type, name, description, parameters}`,
#     ne wrapper `{type:"function", function:{...}}`.
# ---------------------------------------------------------------------------

# Modely které podporují reasoning_effort (grok-4 a jeho vyladěné varianty NE)
_XAI_REASONING_EFFORT_UNSUPPORTED = {"grok-4", "grok-4-0709"}

_XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"


def _xai_is_reasoning(model: str) -> bool:
    """Reasoning modely mají v ID 'reasoning' nebo jsou multi-agent."""
    m = model.lower()
    return "reasoning" in m or "multi-agent" in m or m == "grok-3-mini"


def _xai_supports_reasoning_effort(model: str) -> bool:
    if not _xai_is_reasoning(model):
        return False
    m = model.lower()
    if m in _XAI_REASONING_EFFORT_UNSUPPORTED:
        return False
    if m.startswith("grok-4-") and "fast" not in m and "1-fast" not in m:
        # vanilla grok-4 varianty nepodporují
        return False
    return True


def _xai_input_from_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
    """Konvertuje naše ChatMessage na Responses API `input` array.

    Responses API má dvě cesty:
      * `instructions` (string) — system prompt
      * `input` (array) — heterogeneous list:
          - `{role: "user"|"assistant", content: str}` — běžné zprávy
          - `{type: "function_call", call_id, name, arguments}` — předchozí tool call asistenta
          - `{type: "function_call_output", call_id, output}` — výsledek tool callu

    Naše interní formáty:
      * Messages mohou nést `_raw_openai` (OpenAI Chat Completions message dict).
        Pro role="tool": `{role:"tool", tool_call_id, content}` → function_call_output
        Pro role="assistant" s tool_calls: `{role:"assistant", tool_calls:[...]}` → series of function_call
      * Plain `{role, content}` jdou přímo.

    Returns:
        (system_text_or_None, input_array)
    """
    system_text: str | None = None
    items: list[dict] = []

    for m in messages:
        raw = m._raw_openai
        if raw is not None:
            role = raw.get("role")
            if role == "system":
                # Responses API nemá role="system" v input — použij instructions
                if system_text is None:
                    system_text = raw.get("content") or ""
                else:
                    system_text += "\n\n" + (raw.get("content") or "")
                continue
            if role == "tool":
                # tool_result → function_call_output
                items.append({
                    "type": "function_call_output",
                    "call_id": raw.get("tool_call_id", ""),
                    "output": raw.get("content") or "",
                })
                continue
            if role == "assistant" and raw.get("tool_calls"):
                # Pokud má assistant text + tool_calls, oboje musíme přidat
                content = raw.get("content")
                if content:
                    items.append({"role": "assistant", "content": content})
                for tc in raw.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    items.append({
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "") or "{}",
                    })
                continue
            # Běžná text message
            items.append({"role": role or "user", "content": raw.get("content") or ""})
        else:
            if m.role == "system":
                if system_text is None:
                    system_text = m.content
                else:
                    system_text += "\n\n" + m.content
            else:
                items.append({"role": m.role, "content": m.content})

    return system_text, items


def _xai_tools_to_responses(tools: list[dict]) -> list[dict]:
    """Konvertuje OpenAI Chat Completions tool schema → Responses API formát.

    Vstup: `[{"type":"function","function":{"name","description","parameters"}}, ...]`
    Výstup: `[{"type":"function","name","description","parameters"}, ...]`
    Položky které už jsou ve flat formátu nebo `web_search` necháme být.
    """
    out: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        ttype = t.get("type")
        if ttype == "function" and "function" in t:
            fn = t["function"]
            out.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        elif ttype == "function":
            # už flat
            out.append(t)
        elif ttype in ("web_search", "web_search_preview"):
            out.append(t)
        else:
            # neznámý typ — předáme jak je
            out.append(t)
    return out


def _xai_build_body(
    messages: list[ChatMessage],
    model: str,
    temperature: float,
    max_tokens: int,
    xai: XaiOptions,
    *,
    tools: list[dict] | None = None,
    stream: bool = False,
) -> dict:
    """Sestaví request body pro POST /v1/responses."""
    system_text, input_items = _xai_input_from_messages(messages)
    body: dict = {
        "model": model,
        "input": input_items,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system_text:
        body["instructions"] = system_text
    if stream:
        body["stream"] = True
    if xai.reasoning_effort and _xai_supports_reasoning_effort(model):
        body["reasoning"] = {"effort": xai.reasoning_effort}

    # Tools: function tools + případně server-side web_search.
    # Live Search (search_parameters) je deprecated; náhrada je web_search tool.
    out_tools: list[dict] = []
    if tools:
        out_tools.extend(_xai_tools_to_responses(tools))
    if xai.search.enabled and xai.search.mode != "off":
        # Přidat web_search jako server-side tool. Grok ho zavolá sám podle
        # potřeby; výsledky vrátí jako annotations v output messagi.
        out_tools.append({"type": "web_search"})
    if out_tools:
        body["tools"] = out_tools
    return body


def _xai_extract_from_response(data: dict, model: str) -> tuple[str, list[ToolCall], UsageInfo, str | None]:
    """Vyparsuje Responses API JSON: text, tool_calls, usage, status.

    Vrací: (assistant_text, tool_calls, usage_info, status)
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    citations: list[str] = []

    for item in data.get("output", []) or []:
        itype = item.get("type")
        if itype == "message":
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    text_parts.append(c.get("text", "") or "")
                    for ann in c.get("annotations", []) or []:
                        if ann.get("type") == "url_citation":
                            url = ann.get("url")
                            if url and url not in citations:
                                citations.append(url)
        elif itype == "function_call":
            args_str = item.get("arguments") or "{}"
            try:
                args = json.loads(args_str) if args_str else {}
            except Exception:
                args = {}
            tool_calls.append(ToolCall(
                name=item.get("name", ""),
                args=args,
                tool_call_id=item.get("call_id") or item.get("id", ""),
            ))
        # web_search_call, reasoning, ... — ignorujeme (jen telemetrie)

    info = UsageInfo()
    u = data.get("usage") or {}
    info.input_tokens = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
    info.output_tokens = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
    out_details = u.get("output_tokens_details") or u.get("completion_tokens_details") or {}
    info.reasoning_tokens = int(out_details.get("reasoning_tokens") or 0)
    in_details = u.get("input_tokens_details") or u.get("prompt_tokens_details") or {}
    info.cached_input_tokens = int(in_details.get("cached_tokens") or 0)
    info.num_sources_used = int(u.get("num_sources_used") or 0)
    if citations:
        info.citations = citations
    status = data.get("status")
    return "".join(text_parts), tool_calls, info, status


async def _xai_responses_post(body: dict, *, timeout: float = 120.0) -> dict:
    """Zavolá POST /v1/responses a vrátí parsed JSON. Hází APIError při non-200."""
    import httpx
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(_XAI_RESPONSES_URL, headers=headers, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"xAI /v1/responses HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


async def _xai_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int,
    xai: XaiOptions,
) -> ChatResponse:
    body = _xai_build_body(messages, model, temperature, max_tokens, xai)
    data = await _xai_responses_post(body)
    text, _calls, usage, status = _xai_extract_from_response(data, model)
    if usage.reasoning_tokens or status == "incomplete" or usage.num_sources_used:
        log.info(
            "XAI_USAGE model=%s in=%d out=%d reasoning=%d cached=%d sources=%d cits=%d status=%s",
            model, usage.input_tokens, usage.output_tokens, usage.reasoning_tokens,
            usage.cached_input_tokens, usage.num_sources_used, len(usage.citations), status,
        )
    return ChatResponse(content=text, model=model, provider="xai", usage=usage)


async def _xai_chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict],
    temperature: float,
    max_tokens: int,
    xai: XaiOptions,
) -> ToolCallResult:
    """xAI tool calling přes Responses API.

    Function tools (file/email/MCP) jdou ve flat formátu. Pokud je
    `xai.search.enabled`, přidáváme i server-side `web_search` tool — Grok
    si sám rozhodne kdy ho použít a vrátí citations v annotations message itemu.
    """
    body = _xai_build_body(messages, model, temperature, max_tokens, xai, tools=tools)
    body["tool_choice"] = "auto"
    try:
        data = await _xai_responses_post(body)
    except Exception as exc:
        log.warning("XAI_TOOL_CALL_FAILED %s: %s — fallback bez toolů", type(exc).__name__, exc)
        resp_obj = await _xai_chat(messages, model, temperature, max_tokens, xai)
        return ToolCallResult(tool_calls=[], direct_content=resp_obj.content, usage=resp_obj.usage)

    text, calls, usage, status = _xai_extract_from_response(data, model)
    if calls:
        log.debug("XAI_TOOL_CALLS status=%r calls=%d", status, len(calls))
        return ToolCallResult(tool_calls=calls, direct_content=None, usage=usage)
    log.debug("XAI_DIRECT status=%r content_len=%d sources=%d",
              status, len(text), usage.num_sources_used)
    return ToolCallResult(tool_calls=[], direct_content=text, usage=usage)


async def _xai_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int,
    xai: XaiOptions,
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    """Streamuje text z Responses API přes SSE.

    Responses API streaming events (jen relevantní):
      * `response.output_text.delta` — `{type, delta, ...}` přírůstek textu
      * `response.completed` — `{type, response: {...full response...}}` finální stav s usage
      * `response.failed` / `response.incomplete` — chyby
    Ostatní eventy (output_item.added/done, content_part.*, web_search_call.*,
    reasoning.*) ignorujeme pro účely token streamu.

    Yields: (delta_text, None) pro každý chunk; pak ("", UsageInfo) na konci.
    """
    import httpx

    body = _xai_build_body(messages, model, temperature, max_tokens, xai, stream=True)
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    info = UsageInfo()
    citations: list[str] = []
    status: str | None = None

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", _XAI_RESPONSES_URL, headers=headers, json=body) as r:
            if r.status_code != 200:
                err_body = (await r.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"xAI /v1/responses stream HTTP {r.status_code}: {err_body[:500]}")
            event_data = ""
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    event_data = line[5:].strip()
                    if event_data == "[DONE]":
                        continue
                    try:
                        ev = json.loads(event_data)
                    except Exception:
                        continue
                    etype = ev.get("type")
                    if etype == "response.output_text.delta":
                        delta = ev.get("delta") or ""
                        if delta:
                            yield (delta, None)
                    elif etype == "response.completed":
                        resp = ev.get("response") or {}
                        # Vyparsuj usage + citations z final stavu
                        _t, _calls, finfo, status = _xai_extract_from_response(resp, model)
                        info = finfo
                        if finfo.citations:
                            citations = finfo.citations
                    elif etype in ("response.failed", "response.incomplete"):
                        status = etype
                # prázdné řádky / event:* ignorujeme

    if citations and not info.citations:
        info.citations = citations
    if info.reasoning_tokens or status in ("response.failed", "response.incomplete") or info.num_sources_used:
        log.info(
            "XAI_USAGE model=%s in=%d out=%d reasoning=%d cached=%d sources=%d cits=%d status=%s",
            model, info.input_tokens, info.output_tokens, info.reasoning_tokens,
            info.cached_input_tokens, info.num_sources_used, len(info.citations), status,
        )
    yield ("", info)
