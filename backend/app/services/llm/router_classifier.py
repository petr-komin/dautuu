"""Routing classifier — rozhodne kam jít pro kontext před hlavním LLM voláním.

Volá levný/rychlý model s strict-JSON system promptem a vrátí strukturované
rozhodnutí: hledat na webu? v historii konverzací? v emailech?

Použití:
    decision = await classify_query(query, recent_messages)
    if decision.web: ...
    if decision.history: ...
    if decision.email: ...

Při selhání (timeout, JSON parse error) vrátí bezpečný fallback
(history=True, ostatní False) a zaloguje warning.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from app.core.config import settings
from app.services.llm.router import ChatMessage, chat

log = logging.getLogger("dautuu.llm.classifier")


@dataclass
class ClassifierDecision:
    web: bool = False
    history: bool = True
    email: bool = False
    reasoning: str = ""
    # diagnostika
    took_ms: int = 0
    fallback: bool = False


_SYSTEM_PROMPT = """Jsi klasifikátor uživatelských dotazů pro chat asistenta. Rozhoduj KAM jít pro kontext:

- "web": dotaz vyžaduje aktuální informace z internetu (zprávy, dnešní data, ceny, počasí, novinky, fakta o veřejných osobnostech/firmách v reálném čase, dokumentace knihoven). Vyber když dotaz obsahuje slova jako "dnes", "aktuálně", "nedávno", "co je nového", konkrétní data v poslední době, nebo se ptá na info které se rychle mění.

- "history": dotaz odkazuje na předchozí konverzace s uživatelem ("co jsme řešili minule", "jak jsme to dělali", "pamatuj si že", odkaz na dřívější rozhodnutí). Vyber TAKÉ když dotaz působí jako pokračování tématu i bez explicitního odkazu.

- "email": dotaz se týká uživatelových emailů, korespondence, "co mi psal X", "kdy jsem dostal", "shrnutí mailů od".

Pravidla:
- Můžeš vybrat víc kategorií najednou (např. web+history pro "jaký byl výsledek X co jsme nedávno řešili?").
- Pokud dotaz vystačí s obecnými znalostmi LLM (programátorské how-to, definice, překlady, jednoduché výpočty) → všechny false.
- Buď konzervativní u "web" (drahé) ale velkorysý u "history" (levné, často užitečné).

ODPOVĚZ VÝHRADNĚ VALIDNÍM JSON na jednom řádku, nic dalšího:
{"web": bool, "history": bool, "email": bool, "reasoning": "krátké česky max 1 věta"}"""


_FEW_SHOT: list[tuple[str, dict]] = [
    (
        "jaký je dnes kurz dolaru?",
        {"web": True, "history": False, "email": False, "reasoning": "Aktuální kurz vyžaduje web."},
    ),
    (
        "napiš mi funkci v Pythonu která reverze řetězec",
        {"web": False, "history": False, "email": False, "reasoning": "Obecná programátorská úloha."},
    ),
    (
        "jak jsme včera řešili ten bug s autentikací?",
        {"web": False, "history": True, "email": False, "reasoning": "Odkaz na předchozí konverzaci."},
    ),
    (
        "shrň mi nejnovější emaily od šéfa",
        {"web": False, "history": False, "email": True, "reasoning": "Dotaz na emaily."},
    ),
    (
        "co píše Apple o novém M5 chipu a jak to navazuje na to co jsme probírali?",
        {"web": True, "history": True, "email": False, "reasoning": "Aktuální info + odkaz na minulou konverzaci."},
    ),
]


def _build_messages(query: str, recent: list[ChatMessage] | None) -> list[ChatMessage]:
    msgs: list[ChatMessage] = [ChatMessage(role="system", content=_SYSTEM_PROMPT)]
    for q, ans in _FEW_SHOT:
        msgs.append(ChatMessage(role="user", content=q))
        msgs.append(ChatMessage(role="assistant", content=json.dumps(ans, ensure_ascii=False)))

    # Přidej kontext z posledních ~3 zpráv aktuální konverzace (pomáhá rozeznat pokračování tématu)
    if recent:
        ctx_lines: list[str] = []
        for m in recent[-3:]:
            if m.role in ("user", "assistant") and m.content:
                snippet = m.content[:200].replace("\n", " ")
                ctx_lines.append(f"{m.role}: {snippet}")
        if ctx_lines:
            ctx = "Předchozí kontext této konverzace:\n" + "\n".join(ctx_lines) + "\n\nNový dotaz: " + query
            msgs.append(ChatMessage(role="user", content=ctx))
        else:
            msgs.append(ChatMessage(role="user", content=query))
    else:
        msgs.append(ChatMessage(role="user", content=query))

    return msgs


_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    # Zkus rovnou
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Vytáhni první {...} blok (model může přidat code-fence nebo prefix)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


async def classify_query(
    query: str,
    recent_messages: list[ChatMessage] | None = None,
) -> ClassifierDecision:
    """Klasifikuje dotaz a rozhodne o kontextu.

    Args:
        query: Aktuální user dotaz.
        recent_messages: Posledních ~3 zpráv konverzace (volitelné, pomáhá s pokračováním tématu).

    Returns:
        ClassifierDecision se třemi bool flagy. Při chybě vrátí fallback (history=True).
    """
    t0 = time.perf_counter()
    messages = _build_messages(query, recent_messages)

    try:
        resp = await asyncio.wait_for(
            chat(
                messages=messages,
                model=settings.classifier_model,
                provider=settings.classifier_provider,  # type: ignore[arg-type]
                temperature=0.0,
                max_tokens=settings.classifier_max_tokens,
            ),
            timeout=settings.classifier_timeout_s,
        )
    except asyncio.TimeoutError:
        took = int((time.perf_counter() - t0) * 1000)
        log.warning("CLASSIFIER timeout took=%dms — using fallback", took)
        return ClassifierDecision(web=False, history=True, email=False, reasoning="timeout fallback", took_ms=took, fallback=True)
    except Exception as e:
        took = int((time.perf_counter() - t0) * 1000)
        log.warning("CLASSIFIER error took=%dms err=%r — using fallback", took, e)
        return ClassifierDecision(web=False, history=True, email=False, reasoning=f"error: {e}", took_ms=took, fallback=True)

    took = int((time.perf_counter() - t0) * 1000)
    parsed = _parse_json(resp.content)
    if not parsed or not isinstance(parsed, dict):
        log.warning("CLASSIFIER unparseable response took=%dms raw=%r — using fallback", took, resp.content[:200])
        return ClassifierDecision(web=False, history=True, email=False, reasoning="unparseable", took_ms=took, fallback=True)

    decision = ClassifierDecision(
        web=bool(parsed.get("web", False)),
        history=bool(parsed.get("history", True)),
        email=bool(parsed.get("email", False)),
        reasoning=str(parsed.get("reasoning", ""))[:300],
        took_ms=took,
        fallback=False,
    )
    log.info(
        "CLASSIFIER took=%dms web=%s history=%s email=%s reason=%s",
        decision.took_ms, decision.web, decision.history, decision.email, decision.reasoning,
    )
    return decision
