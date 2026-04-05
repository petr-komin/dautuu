"""Ceníky AI modelů — ceny v USD za 1 milion tokenů / jednotku.

Aktualizováno: 2026-04-01

Zdroje:
  Together AI  — https://together.ai/pricing
  Anthropic    — https://www.anthropic.com/pricing
  OpenAI       — https://openai.com/pricing
  Tavily       — https://tavily.com/#pricing

Struktura:
  CHAT_PRICING[provider][model] = {"input": float, "output": float}   ← $/M tokenů
  EMBEDDING_PRICING[provider][model] = float                          ← $/M tokenů
  IMAGE_PRICING[provider][model] = float                              ← $/obrázek nebo $/megapixel
  TTS_PRICING[provider][model] = float                                ← $/M znaků
  STT_PRICING[provider][model] = float                                ← $/minutu
  SEARCH_PRICING[provider][depth] = float                             ← $/1000 requestů

Ollama (lokální) nemá cenu — vrátíme None.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Chat / text completion  ($/M tokenů)
# ---------------------------------------------------------------------------

CHAT_PRICING: dict[str, dict[str, dict[str, float]]] = {
    "together": {
        # Meta Llama
        "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8":         {"input": 0.27,  "output": 0.85},
        "meta-llama/Llama-3.3-70B-Instruct-Turbo":                   {"input": 0.88,  "output": 0.88},
        "meta-llama/Llama-3.1-70B-Instruct-Turbo":                   {"input": 0.88,  "output": 0.88},
        "meta-llama/Llama-3.1-8B-Instruct-Turbo":                    {"input": 0.10,  "output": 0.10},
        "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo":             {"input": 3.50,  "output": 3.50},
        # DeepSeek
        "deepseek-ai/DeepSeek-V3.1":                                  {"input": 0.60,  "output": 1.70},
        "deepseek-ai/DeepSeek-V3":                                    {"input": 0.60,  "output": 1.70},
        "deepseek-ai/DeepSeek-R1-0528":                               {"input": 3.00,  "output": 7.00},
        "deepseek-ai/DeepSeek-R1":                                    {"input": 3.00,  "output": 7.00},
        # Qwen
        "Qwen/Qwen3.5-397B-A17B":                                    {"input": 0.60,  "output": 3.60},
        "Qwen/Qwen3.5-9B":                                            {"input": 0.10,  "output": 0.15},
        "Qwen/Qwen3-235B-A22B-Instruct-2507-tput":                   {"input": 0.20,  "output": 0.60},
        "Qwen/Qwen3-235B-A22B-Thinking-2507":                        {"input": 0.65,  "output": 3.00},
        "Qwen/Qwen3-Next-80B-A3B-Instruct":                          {"input": 0.15,  "output": 1.50},
        "Qwen/Qwen3-Next-80B-A3B-Thinking":                          {"input": 0.15,  "output": 1.50},
        "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8":                   {"input": 2.00,  "output": 2.00},
        "Qwen/Qwen3-Coder-Next-FP8":                                  {"input": 0.50,  "output": 1.20},
        "Qwen/Qwen3-VL-32B-Instruct":                                 {"input": 0.50,  "output": 1.50},
        "Qwen/Qwen3-VL-8B-Instruct":                                  {"input": 0.18,  "output": 0.68},
        "Qwen/Qwen2.5-7B-Instruct-Turbo":                            {"input": 0.30,  "output": 0.30},
        "Qwen/Qwen2.5-72B-Instruct-Turbo":                           {"input": 1.20,  "output": 1.20},
        "Qwen/Qwen2.5-72B-Instruct":                                  {"input": 1.20,  "output": 1.20},
        "Qwen/Qwen2.5-Coder-32B-Instruct":                           {"input": 0.80,  "output": 0.80},
        "Qwen/Qwen2.5-14B-Instruct":                                  {"input": 0.80,  "output": 0.80},
        "Qwen/Qwen2-VL-72B-Instruct":                                 {"input": 1.20,  "output": 1.20},
        "Qwen/Qwen2.5-VL-72B-Instruct":                              {"input": 1.95,  "output": 8.00},
        "Qwen/QwQ-32B":                                               {"input": 1.20,  "output": 1.20},
        # Mistral
        "mistralai/Mistral-7B-Instruct-v0.2":                        {"input": 0.20,  "output": 0.20},
        "mistralai/Mistral-7B-Instruct-v0.3":                        {"input": 0.20,  "output": 0.20},
        "mistralai/Mixtral-8x7B-Instruct-v0.1":                      {"input": 0.60,  "output": 0.60},
        "mistralai/Mixtral-8x22B-Instruct-v0.1":                     {"input": 1.20,  "output": 1.20},
        "mistralai/Mistral-Small-24B-Instruct-2501":                  {"input": 0.10,  "output": 0.30},
        # GLM / ZhipuAI
        "THUDM/glm-4-9b-chat":                                        {"input": 0.10,  "output": 0.10},
        "ZhipuAI/GLM-5":                                              {"input": 1.00,  "output": 3.20},
        # Kimi
        "moonshotai/Kimi-K2.5":                                       {"input": 0.50,  "output": 2.80},
        "moonshotai/Kimi-K2-Instruct":                                {"input": 1.00,  "output": 3.00},
        # MiniMax
        "MiniMaxAI/MiniMax-M2.5":                                     {"input": 0.30,  "output": 1.20},
        # Google Gemma
        "google/gemma-3n-E4B-it":                                     {"input": 0.02,  "output": 0.04},
        # OpenAI přes Together
        "openai/gpt-oss-120b":                                        {"input": 0.15,  "output": 0.60},
    },
    "openai": {
        "gpt-4o":                  {"input": 2.50,  "output": 10.00},
        "gpt-4o-mini":             {"input": 0.15,  "output": 0.60},
        "o3-mini":                 {"input": 1.10,  "output": 4.40},
        "o3":                      {"input": 10.00, "output": 40.00},
        "o4-mini":                 {"input": 1.10,  "output": 4.40},
        "gpt-4.1":                 {"input": 2.00,  "output": 8.00},
        "gpt-4.1-mini":            {"input": 0.40,  "output": 1.60},
        "gpt-4.1-nano":            {"input": 0.10,  "output": 0.40},
    },
    "anthropic": {
        # Aktuální generace
        "claude-opus-4-6":         {"input": 5.00,  "output": 25.00},
        "claude-sonnet-4-6":       {"input": 3.00,  "output": 15.00},
        "claude-haiku-4-5":        {"input": 1.00,  "output": 5.00},
        # Starší
        "claude-opus-4-5":         {"input": 5.00,  "output": 25.00},
        "claude-sonnet-4-5":       {"input": 3.00,  "output": 15.00},
        "claude-haiku-3-5":        {"input": 1.00,  "output": 5.00},
        "claude-haiku-3":          {"input": 0.25,  "output": 1.25},
        "claude-opus-4-1":         {"input": 15.00, "output": 75.00},
        "claude-sonnet-4":         {"input": 3.00,  "output": 15.00},
        "claude-opus-4":           {"input": 15.00, "output": 75.00},
    },
    # Ollama — lokální, cena = None
    "ollama": {},
}

# ---------------------------------------------------------------------------
# Embeddings  ($/M tokenů)
# ---------------------------------------------------------------------------

EMBEDDING_PRICING: dict[str, dict[str, float]] = {
    "together": {
        "intfloat/multilingual-e5-large-instruct": 0.02,
        "togethercomputer/m2-bert-80M-8k-retrieval": 0.008,
    },
    "openai": {
        "text-embedding-3-small": 0.02,
        "text-embedding-3-large": 0.13,
        "text-embedding-ada-002": 0.10,
    },
}

# ---------------------------------------------------------------------------
# Obrázky  ($/obrázek — výchozí rozlišení/kvalita)
# Budoucí použití
# ---------------------------------------------------------------------------

IMAGE_PRICING: dict[str, dict[str, float]] = {
    "together": {
        "black-forest-labs/FLUX.2-dev":    0.0154,
        "black-forest-labs/FLUX.2-pro":    0.03,
        "black-forest-labs/FLUX.2-max":    0.07,
        "black-forest-labs/FLUX.1-schnell-Free": 0.0,
        "black-forest-labs/FLUX.1.1-pro":  0.04,
        "stabilityai/stable-diffusion-xl-base-1.0": 0.002,
    },
    "openai": {
        "dall-e-3": 0.04,       # 1024×1024 standard
        "dall-e-2": 0.02,       # 1024×1024
        "gpt-image-1": 0.034,
    },
}

# ---------------------------------------------------------------------------
# TTS — text-to-speech  ($/M znaků)
# Budoucí použití
# ---------------------------------------------------------------------------

TTS_PRICING: dict[str, dict[str, float]] = {
    "together": {
        "cartesia/sonic-2": 65.0,
        "cartesia/sonic-3": 65.0,
    },
    "openai": {
        "tts-1":    15.0,
        "tts-1-hd": 30.0,
    },
}

# ---------------------------------------------------------------------------
# STT — speech-to-text  ($/minutu)
# Budoucí použití
# ---------------------------------------------------------------------------

STT_PRICING: dict[str, dict[str, float]] = {
    "together": {
        "openai/whisper-large-v3": 0.0015,  # per audio minute
    },
    "openai": {
        "whisper-1": 0.006,
    },
}

# ---------------------------------------------------------------------------
# Web Search  ($/1000 requestů)
# ---------------------------------------------------------------------------

SEARCH_PRICING: dict[str, dict[str, float]] = {
    "tavily": {
        # search_depth parametr = "basic" nebo "advanced"
        "basic":    5.0,   # $5 / 1000 requestů
        "advanced": 10.0,  # $10 / 1000 requestů
    },
}


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def get_chat_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Vrátí cenu v USD pro chat volání. None = lokální/neznámý model."""
    prices = CHAT_PRICING.get(provider, {}).get(model)
    if prices is None:
        # Fallback: zkusíme hledat podle suffixu (Together vrací různé varianty ID)
        for key, p in CHAT_PRICING.get(provider, {}).items():
            if model.endswith(key) or key.endswith(model.split("/")[-1]):
                prices = p
                break
    if prices is None:
        return None
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def get_embedding_cost(provider: str, model: str, input_tokens: int) -> float | None:
    """Vrátí cenu v USD pro embedding volání. None = neznámý model."""
    price = EMBEDDING_PRICING.get(provider, {}).get(model)
    if price is None:
        return None
    return input_tokens * price / 1_000_000


def get_search_cost(provider: str, search_depth: str = "basic", num_requests: int = 1) -> float | None:
    """Vrátí cenu v USD pro web search requesty. None = neznámý provider."""
    price_per_1k = SEARCH_PRICING.get(provider, {}).get(search_depth)
    if price_per_1k is None:
        return None
    return num_requests * price_per_1k / 1000
