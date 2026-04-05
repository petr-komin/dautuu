"""LLM Router — jednotné rozhraní pro různé providery.

Podporované providery:
  - together   (primární)
  - openai
  - anthropic
  - ollama
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings

log = logging.getLogger("dautuu.llm.router")

Provider = Literal["together", "openai", "anthropic", "ollama"]


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


@dataclass
class ChatResponse:
    content: str
    model: str
    provider: Provider
    usage: UsageInfo = field(default_factory=UsageInfo)


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
) -> ChatResponse:
    """Pošle zprávy zvolenému LLM a vrátí odpověď."""
    if provider == "together":
        return await _together_chat(messages, model, temperature, max_tokens)
    if provider == "openai":
        return await _openai_chat(messages, model, temperature, max_tokens)
    if provider == "anthropic":
        return await _anthropic_chat(messages, model, temperature, max_tokens)
    if provider == "ollama":
        return await _ollama_chat(messages, model, temperature, max_tokens)
    raise ValueError(f"Neznámý provider: {provider}")


async def chat_with_tools(
    messages: list[ChatMessage],
    model: str,
    provider: Provider = "together",
    tools: list[dict] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> ToolCallResult:
    """LLM volání s tool definicemi — zjistí zda LLM chce volat tool(y).

    Vrátí ToolCallResult:
    - Pokud LLM chce zavolat tool(y): tool_calls je neprázdné
    - Pokud LLM odpověděl přímo: direct_content je vyplněn, tool_calls je []
    """
    if not tools:
        resp = await chat(messages, model, provider, temperature, max_tokens)
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
