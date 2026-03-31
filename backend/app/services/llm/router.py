"""LLM Router — jednotné rozhraní pro různé providery.

Podporované providery:
  - together   (primární)
  - openai
  - anthropic
  - ollama
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings

Provider = Literal["together", "openai", "anthropic", "ollama"]


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


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

    Yields: (chunk_text, None) pro každý token; pak (\"\" , UsageInfo) jako poslední yield
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
    return [{"role": m.role, "content": m.content} for m in messages]


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

async def _openai_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in messages],  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or ""
    usage = UsageInfo(
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
    )
    return ChatResponse(content=content, model=model, provider="openai", usage=usage)


async def _openai_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    usage = UsageInfo()
    s = await client.chat.completions.create(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in messages],  # type: ignore[arg-type]
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

def _split_system(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    """Anthropic přijímá system prompt zvlášť."""
    system = ""
    rest: list[ChatMessage] = []
    for m in messages:
        if m.role == "system":
            system += m.content + "\n"
        else:
            rest.append(m)
    return system.strip(), rest


async def _anthropic_chat(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> ChatResponse:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, rest = _split_system(messages)
    kwargs: dict = dict(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in rest],
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


async def _anthropic_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, rest = _split_system(messages)
    kwargs: dict = dict(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in rest],
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
        "messages": [{"role": m.role, "content": m.content} for m in messages],
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


async def _ollama_stream_with_usage(
    messages: list[ChatMessage], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[tuple[str, UsageInfo | None], None]:
    import httpx
    import json

    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
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
