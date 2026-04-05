import uuid
import logging
import time
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Literal

from app.api.deps import get_current_user
from app.db.session import get_db, AsyncSessionLocal
from app.db.models import User, Conversation, Message, Project
from app.services.llm.router import (
    chat, chat_with_tools, stream_with_usage,
    ChatMessage, Provider, ToolCall,
)
from app.services.rag.memory import index_message, maybe_summarize, retrieve_memory
from app.services.usage.logger import log_chat_usage, log_search_usage
from app.services.tools.search import (
    search_web, format_search_results,
    SEARCH_TOOL_OPENAI, SEARCH_TOOL_ANTHROPIC, SearchMeta,
)
from app.services.tools.email_search import (
    search_emails, format_email_results,
    EMAIL_SEARCH_TOOL_OPENAI, EMAIL_SEARCH_TOOL_ANTHROPIC,
    retrieve_email_memory,
)
from app.services.tools.files import (
    dispatch_file_tool,
    FILE_TOOLS_OPENAI, FILE_TOOLS_ANTHROPIC, FILE_TOOL_NAMES,
)
from app.services.mcp_client import get_user_mcp_tools, call_mcp_tool, parse_server_from_tool_name
from app.core.config import settings

log = logging.getLogger("dautuu.chat")

router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
DEFAULT_PROVIDER: Provider = "together"

SYSTEM_PROMPT = (
    "Jsi osobní AI asistent. Jsi přátelský, přesný a užitečný. "
    "Pokud nevíš odpověď, řekni to upřímně.\n\n"
    "Máš k dispozici nástroje (tools) — používej je AKTIVNĚ a BEZ PTANÍ:\n"
    "- search_web: Kdykoliv otázka vyžaduje aktuální informace (novinky, počasí, kurzy, "
    "ceny, události, osoby, firmy, technologie vydané po roce 2023) — OKAMŽITĚ zavolej "
    "search_web. NEPTEJ SE uživatele zda smíš hledat. Prostě hledej.\n"
    "- read_file, write_file, list_files, create_directory, delete_file: Používej kdykoliv "
    "uživatel chce pracovat se soubory nebo to z kontextu vyplývá.\n\n"
    "PRAVIDLA PRO PRÁCI SE SOUBORY:\n"
    "- Všechny soubory jsou uloženy v pracovním adresáři /workspace.\n"
    "- Cesty VŽDY zadávej relativně, bez úvodního lomítka. Správně: 'soubor.txt', 'slozka/soubor.txt'. "
    "NIKDY nezadávej absolutní cesty jako '/workspace/...' nebo '/home/...'.\n"
    "- Pokud dostaneš chybu o oprávněních nebo přístupu, NEPKOUŠEJ se o jinou absolutní cestu. "
    "Zkontroluj že cesta je relativní a zkus znovu.\n\n"
    "- search_emails: Kdykoliv uživatel zmiňuje emaily, zprávy, korespondenci nebo chce "
    "najít konkrétní email — OKAMŽITĚ zavolej search_emails BEZ PTANÍ. "
    "Hledej i přes část jména nebo domény (např. dotaz 'ponechal' → query='ponechal', "
    "'od Alzy' → from_filter='alza'). "
    "Po nalezení emailů VŽDY shrň jejich obsah srozumitelně: co chtěl odesílatel, "
    "o čem email byl, jaká byla odpověď — nejen vypiš metadata. "
    "Pokud přišlo víc emailů na stejné téma, seskup je a shrň dohromady.\n\n"
    "PRAVIDLO PRO OPAKOVANÉ HLEDÁNÍ:\n"
    "Pokud uživatel zpochybní výsledek hledání — řekne například 'to není správně', "
    "'podívej se znovu', 'to není ono', 'zkus jinak', 'to není ta osoba', "
    "'jak se vlastně jmenuje' nebo podobně — VŽDY zavolej příslušný tool znovu "
    "s upravenou nebo rozšířenou query. Nikdy neargumentuj že máš výsledek správně "
    "aniž bys nejdřív zkusil znovu. Pokud máš v výsledcích konkrétní data (jméno, "
    "email, firma), ověř je a uveď přesně jak jsou v záznamu.\n\n"
    "Pravidlo: Raději zavolej tool zbytečně než se ptát uživatele na svolení."
)

# Maximální počet kol agentic loopu (ochrana před nekonečnou smyčkou)
MAX_TOOL_ROUNDS = 6


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    title: str = "Nová konverzace"
    project_id: uuid.UUID | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    project_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str
    model: str = DEFAULT_MODEL
    provider: Provider = DEFAULT_PROVIDER
    stream: bool = True
    web_search: bool = True
    project_id: uuid.UUID | None = None  # pro nové konverzace bez conversation_id


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    model: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Background úlohy (spouštějí se s vlastní DB session)
# ---------------------------------------------------------------------------

async def _bg_index_and_summarize(message_id: uuid.UUID, conv_id: uuid.UUID) -> None:
    """Zaindexuje zprávu a případně sumarizuje konverzaci — běží po streamu."""
    async with AsyncSessionLocal() as db:
        await index_message(message_id, db)
        await maybe_summarize(conv_id, db)


# ---------------------------------------------------------------------------
# Helpers pro konverzi DB zpráv na LLM formát
# ---------------------------------------------------------------------------

def _db_messages_to_llm(history: list[Message], provider: str) -> list[ChatMessage]:
    """Převede DB zprávy na ChatMessage seznam pro LLM.

    Zprávy s role='tool_call' a role='tool' se konvertují do formátu specifického
    pro daného providera, aby model viděl historii tool volání z předchozích zpráv.

    OpenAI/Together formát:
      tool_call  → {"role": "assistant", "content": null, "tool_calls": [...]}
      tool       → {"role": "tool", "tool_call_id": "...", "content": "..."}

    Anthropic formát:
      tool_call  → {"role": "assistant", "content": [{"type": "tool_use", "id": ..., "name": ..., "input": ...}]}
      tool       → {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": "..."}]}
    """
    is_anthropic = provider == "anthropic"
    result: list[ChatMessage] = []

    for msg in history:
        if msg.role in ("user", "assistant", "system"):
            result.append(ChatMessage(role=msg.role, content=msg.content or ""))  # type: ignore[arg-type]

        elif msg.role == "tool_call":
            # Zpráva reprezentující assistant tool call kolo
            td = msg.tool_data or {}
            calls = td.get("tool_calls", [])
            if not calls:
                continue

            if is_anthropic:
                content_blocks = []
                for tc in calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("args", {}),
                    })
                raw = {"role": "assistant", "content": content_blocks}
                result.append(ChatMessage(
                    role="assistant", content="",
                    _raw_anthropic=raw,
                ))
            else:
                # OpenAI / Together
                tool_calls_raw = []
                for tc in calls:
                    import json as _json
                    tool_calls_raw.append({
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": _json.dumps(tc.get("args", {}), ensure_ascii=False),
                        },
                    })
                raw = {"role": "assistant", "content": None, "tool_calls": tool_calls_raw}
                result.append(ChatMessage(
                    role="assistant", content="",
                    _raw_openai=raw,
                ))

        elif msg.role == "tool":
            # Výsledek tool callu
            td = msg.tool_data or {}
            tool_call_id = td.get("tool_call_id", "")
            tool_name = td.get("tool_name", "")
            content = msg.content or ""

            if is_anthropic:
                raw = {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": content,
                    }],
                }
                result.append(ChatMessage(
                    role="user", content="",
                    _raw_anthropic=raw,
                ))
            else:
                raw = {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": content,
                }
                result.append(ChatMessage(
                    role="user", content="",
                    _raw_openai=raw,
                ))

    return result


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=current_user.id, title=body.title, project_id=body.project_id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    project_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Conversation).where(Conversation.user_id == current_user.id)
    if project_id is not None:
        q = q.where(Conversation.project_id == project_id)
    result = await db.execute(q.order_by(Conversation.updated_at.desc()))
    return result.scalars().all()


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def assign_conversation(
    conversation_id: uuid.UUID,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Přeřadí konverzaci do jiného projektu (nebo do globálních — project_id: null)."""
    conv = await _get_conversation(conversation_id, current_user.id, db)
    # Explicitně předáváme null → odebrat z projektu; uuid → přiřadit
    project_id = body.get("project_id", "MISSING")
    if project_id != "MISSING":
        conv.project_id = uuid.UUID(project_id) if project_id else None
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _get_conversation(conversation_id, current_user.id, db)
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Posílání zpráv
# ---------------------------------------------------------------------------

@router.post("/send")
async def send_message(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Získáme nebo vytvoříme konverzaci
    if body.conversation_id:
        conv = await _get_conversation(body.conversation_id, current_user.id, db)
    else:
        conv = Conversation(
            user_id=current_user.id,
            title=body.message[:60],
            project_id=body.project_id,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

    # Uložíme uživatelovu zprávu
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # Indexace user zprávy na pozadí
    asyncio.create_task(_bg_index_and_summarize(user_msg.id, conv.id))

    # Načti paměť z minulých konverzací + emailovou historii (paralelně)
    memory, email_memory = await asyncio.gather(
        retrieve_memory(
            query=body.message,
            user_id=current_user.id,
            current_conv_id=conv.id,
            db=db,
        ),
        retrieve_email_memory(query=body.message),
    )

    # Sestavíme historii zpráv pro LLM
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(60)   # víc zpráv — tool_call + tool zabírají extra řádky
    )
    history = history_result.scalars().all()

    # System prompt + instrukce projektu + volitelná paměť z minulých konverzací
    system_content = SYSTEM_PROMPT
    if conv.project_id:
        proj_result = await db.execute(
            select(Project).where(Project.id == conv.project_id, Project.user_id == current_user.id)
        )
        project = proj_result.scalar_one_or_none()
        if project and project.instructions:
            system_content = project.instructions + "\n\n---\n\n" + system_content
    if memory:
        system_content += (
            "\n\n---\nNíže jsou relevantní informace z předchozích konverzací s uživatelem. "
            "Využij je pokud jsou užitečné pro odpověď, ale nezmiňuj explicitně že je čteš.\n\n"
            + memory
        )
    if email_memory:
        system_content += (
            "\n\n---\nNíže jsou emaily z emailové schránky uživatele relevantní k aktuální otázce. "
            "Využij je jako kontext — pokud otázka přímo nesouvisí s emaily, jen je tiše zohledni. "
            "Nezmiňuj explicitně že čteš emaily pokud se tě na to uživatel neptá.\n\n"
            + email_memory
        )

    llm_messages = [ChatMessage(role="system", content=system_content)]
    llm_messages.extend(_db_messages_to_llm(history, body.provider))

    # Streaming odpověď
    if body.stream:
        log.info("STREAM  user=%s conv=%s provider=%s model=%s memory=%s web_search=%s",
                 current_user.id, conv.id, body.provider, body.model, bool(memory), body.web_search)
        return StreamingResponse(
            _stream_and_save(llm_messages, body, conv.id, current_user.id, db),
            media_type="text/event-stream",
            headers={
                "X-Conversation-Id": str(conv.id),
                "Cache-Control": "no-cache",
            },
        )

    # Blokující odpověď — prožeň agentic loopem
    enriched, _ = await _run_tool_loop_no_stream(
        llm_messages, body, on_event=None,
        user_id=current_user.id, conv_id=conv.id, db=db,
    )
    response = await chat(
        messages=enriched,
        model=body.model,
        provider=body.provider,
    )
    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=response.content,
        model=body.model,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    asyncio.create_task(_bg_index_and_summarize(assistant_msg.id, conv.id))
    asyncio.create_task(_bg_log_chat_usage(
        provider=body.provider,
        model=body.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        user_id=current_user.id,
        conversation_id=conv.id,
        message_id=assistant_msg.id,
    ))

    return {
        "conversation_id": str(conv.id),
        "message": {"role": "assistant", "content": response.content, "model": body.model},
    }


# ---------------------------------------------------------------------------
# Agentic tool loop — sdílená logika pro streaming i blokující režim
# ---------------------------------------------------------------------------

async def _get_all_tools(
    provider: Provider,
    web_search_enabled: bool,
    user_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Sestaví seznam všech dostupných tools pro daného providera."""
    tools: list[dict] = []
    is_anthropic = provider == "anthropic"

    # File tools — vždy dostupné (workspace je vždy namountován)
    tools.extend(FILE_TOOLS_ANTHROPIC if is_anthropic else FILE_TOOLS_OPENAI)

    # Web search — jen pokud je Tavily API klíč nastaven a uživatel to chce
    if web_search_enabled and settings.tavily_api_key:
        tools.append(SEARCH_TOOL_ANTHROPIC if is_anthropic else SEARCH_TOOL_OPENAI)

    # Email search — jen pokud je EMAIL_DB_URL nastaven
    if settings.email_db_url:
        tools.append(EMAIL_SEARCH_TOOL_ANTHROPIC if is_anthropic else EMAIL_SEARCH_TOOL_OPENAI)

    # Externí MCP servery uživatele
    if user_id and db:
        mcp_tools = await get_user_mcp_tools(user_id, db, provider)
        tools.extend(mcp_tools)

    return tools


async def _execute_tool_call(
    tc: ToolCall,
    user_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> tuple[str, SearchMeta | None]:
    """Spustí tool call a vrátí (výsledek jako string, search metadata nebo None)."""
    if tc.name == "search_web":
        query = tc.args.get("query", "")
        results, meta = await search_web(query)
        return format_search_results(results), meta
    if tc.name == "search_emails":
        results, _meta = await search_emails(
            query=tc.args.get("query", ""),
            from_filter=tc.args.get("from_filter"),
            folder=tc.args.get("folder"),
            date_from=tc.args.get("date_from"),
            date_to=tc.args.get("date_to"),
        )
        return format_email_results(results), None
    if tc.name in FILE_TOOL_NAMES:
        return dispatch_file_tool(tc.name, tc.args), None
    # Externí MCP tool (má prefix server__)
    if parse_server_from_tool_name(tc.name) and user_id and db:
        result = await call_mcp_tool(tc.name, tc.args, user_id, db)
        return result, None
    return f"[CHYBA] Neznámý tool: {tc.name}", None


async def _run_tool_loop_no_stream(
    llm_messages: list[ChatMessage],
    body: ChatRequest,
    on_event,  # callable(event_type, data) | None — pro non-streaming
    user_id: uuid.UUID | None = None,
    conv_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> tuple[list[ChatMessage], list[str]]:
    """Agentic loop bez streamingu. Vrátí (finální_zprávy, seznam_SSE_eventů_pro_frontend)."""
    tools = await _get_all_tools(body.provider, body.web_search, user_id=user_id, db=db)
    if not tools:
        return llm_messages, []

    messages = list(llm_messages)
    sse_events: list[str] = []

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            result = await chat_with_tools(
                messages=messages,
                model=body.model,
                provider=body.provider,
                tools=tools,
                temperature=0,
                max_tokens=4096,
            )
        except Exception as exc:
            log.warning("TOOL_LOOP_FAILED round=%d %s: %s", _round, type(exc).__name__, exc)
            break

        if not result.tool_calls:
            # Detekce: model vypsal pseudokód tool callu jako text místo skutečného tool callu
            if result.direct_content and any(
                f"{name}(" in (result.direct_content or "")
                for name in ["write_file", "read_file", "list_files", "search_web", "search_emails", "create_directory", "delete_file"]
            ):
                log.warning("TOOL_AS_TEXT round=%d — model vypsal tool call jako text místo volání: %r",
                            _round, (result.direct_content or "")[:200])
            break

        # Zpracuj všechny tool calls tohoto kola
        tool_results_text = []
        tool_outputs_for_db: list[tuple[str, str]] = []
        for tc in result.tool_calls:
            log.info("TOOL_CALL round=%d tool=%r args=%r", _round, tc.name, tc.args)
            if tc.name == "search_web":
                event = f"[SEARCHING:{tc.args.get('query', '')}]"
            elif tc.name == "search_emails":
                event = f"[SEARCHING_EMAIL:{tc.args.get('query', '')}]"
            else:
                event = f"[TOOL:{tc.name}:{tc.args.get('path', tc.args.get('query', ''))}]"
            sse_events.append(event)

            tool_output, search_meta = await _execute_tool_call(tc, user_id=user_id, db=db)
            tool_results_text.append(f"[Tool: {tc.name}]\n{tool_output}")
            tool_outputs_for_db.append((tc.tool_call_id, tool_output))

            # Zaloguj web search usage
            if search_meta is not None:
                asyncio.create_task(_bg_log_search_usage(
                    search_meta=search_meta,
                    user_id=user_id,
                    conv_id=conv_id,
                ))

        # Ulož tool kolo do DB
        if conv_id is not None:
            asyncio.create_task(_save_tool_round(conv_id, result.tool_calls, tool_outputs_for_db))

        # Přidej výsledky toolů jako user zprávu do kontextu
        combined = "\n\n---\n\n".join(tool_results_text)
        messages.append(ChatMessage(
            role="user",
            content=f"[Výsledky nástrojů]\n\n{combined}\n\n"
                    "Pokračuj — použij tyto informace pro odpověď uživateli.",
        ))

    return messages, sse_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_conversation(
    conversation_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konverzace nenalezena")
    return conv


async def _bg_log_chat_usage(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    async with AsyncSessionLocal() as db:
        await log_chat_usage(
            db,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )


async def _bg_log_search_usage(
    *,
    search_meta: SearchMeta,
    user_id: uuid.UUID | None,
    conv_id: uuid.UUID | None,
) -> None:
    async with AsyncSessionLocal() as db:
        await log_search_usage(
            db,
            query=search_meta["query"],
            provider=search_meta["provider"],
            search_depth=search_meta["search_depth"],
            num_results=search_meta["num_results"],
            success=search_meta["success"],
            user_id=user_id,
            conversation_id=conv_id,
        )


async def _save_tool_round(
    conv_id: uuid.UUID,
    tool_calls: list[ToolCall],
    tool_outputs: list[tuple[str, str]],   # [(tool_call_id, output_text), ...]
) -> None:
    """Uloží jedno kolo tool volání do DB: tool_call zpráva + tool výsledky.

    Volá se s vlastní DB session — může běžet jako background task.
    """
    async with AsyncSessionLocal() as db:
        # 1) Zpráva reprezentující co model "řekl" (volal tyto tooly)
        calls_data = [
            {"id": tc.tool_call_id, "name": tc.name, "args": tc.args}
            for tc in tool_calls
        ]
        tool_call_msg = Message(
            conversation_id=conv_id,
            role="tool_call",
            content="",   # obsah je v tool_data
            tool_data={"tool_calls": calls_data},
        )
        db.add(tool_call_msg)

        # 2) Výsledek každého tool callu
        for tc, (tc_id, output) in zip(tool_calls, tool_outputs):
            tool_result_msg = Message(
                conversation_id=conv_id,
                role="tool",
                content=output,
                tool_data={"tool_call_id": tc_id, "tool_name": tc.name},
            )
            db.add(tool_result_msg)

        await db.commit()


async def _stream_and_save(
    llm_messages: list[ChatMessage],
    body: ChatRequest,
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
):
    """Generator pro SSE streaming + uložení + indexace na pozadí.

    Agentic loop:
      1. chat_with_tools() — LLM rozhodne co chce (search, file ops, nic)
      2. Pro každý tool call: pošle SSE event [SEARCHING:...] nebo [TOOL:...],
         spustí tool, přidá výsledek do kontextu
      3. Opakuje až do MAX_TOOL_ROUNDS nebo dokud LLM nevybere žádný tool
      4. stream_with_usage() — finální odpověď streamed uživateli
    """
    full_content = []
    t0 = time.monotonic()
    first_token = True
    final_usage = None

    # --- Agentic tool loop ---
    tools = await _get_all_tools(body.provider, body.web_search, user_id=user_id, db=db)
    messages_to_use = list(llm_messages)

    if tools:
        for _round in range(MAX_TOOL_ROUNDS):
            try:
                tool_result = await chat_with_tools(
                    messages=messages_to_use,
                    model=body.model,
                    provider=body.provider,
                    tools=tools,
                    temperature=0,
                    max_tokens=4096,
                )
            except Exception as exc:
                log.warning("TOOL_LOOP_FAILED round=%d %s: %s", _round, type(exc).__name__, exc)
                break

            if not tool_result.tool_calls:
                # Detekce: model vypsal pseudokód tool callu jako text místo skutečného tool callu
                if tool_result.direct_content and any(
                    f"{name}(" in (tool_result.direct_content or "")
                    for name in ["write_file", "read_file", "list_files", "search_web", "search_emails", "create_directory", "delete_file"]
                ):
                    log.warning("TOOL_AS_TEXT round=%d — model vypsal tool call jako text místo volání: %r",
                                _round, (tool_result.direct_content or "")[:200])
                break

            tool_results_text = []
            tool_outputs_for_db: list[tuple[str, str]] = []
            for tc in tool_result.tool_calls:
                log.info("TOOL_CALL round=%d tool=%r args=%r", _round, tc.name, tc.args)

                # Pošli SSE event — frontend zobrazí indikátor
                if tc.name == "search_web":
                    query = tc.args.get("query", "")
                    yield f"data: [SEARCHING:{query}]\n\n"
                elif tc.name == "search_emails":
                    query = tc.args.get("query", "")
                    yield f"data: [SEARCHING_EMAIL:{query}]\n\n"
                else:
                    path_or_q = tc.args.get("path", tc.args.get("query", ""))
                    yield f"data: [TOOL:{tc.name}:{path_or_q}]\n\n"

                tool_output, search_meta = await _execute_tool_call(tc, user_id=user_id, db=db)
                tool_results_text.append(f"[Tool: {tc.name}]\n{tool_output}")
                tool_outputs_for_db.append((tc.tool_call_id, tool_output))

                # Zaloguj web search usage na pozadí
                if search_meta is not None:
                    asyncio.create_task(_bg_log_search_usage(
                        search_meta=search_meta,
                        user_id=user_id,
                        conv_id=conv_id,
                    ))

            # Ulož tool kolo do DB na pozadí (tool_call + tool výsledky)
            asyncio.create_task(_save_tool_round(conv_id, tool_result.tool_calls, tool_outputs_for_db))

            combined = "\n\n---\n\n".join(tool_results_text)
            messages_to_use.append(ChatMessage(
                role="user",
                content=f"[Výsledky nástrojů]\n\n{combined}\n\n"
                        "Pokračuj — použij tyto informace pro odpověď uživateli.",
            ))

    # --- Streaming finální odpovědi ---
    try:
        async for chunk, usage_info in stream_with_usage(
            messages=messages_to_use,
            model=body.model,
            provider=body.provider,
        ):
            if usage_info is not None:
                final_usage = usage_info
                continue
            if first_token:
                log.info("FIRST_TOKEN  provider=%s model=%s ttft=%.2fs",
                         body.provider, body.model, time.monotonic() - t0)
                first_token = False
            full_content.append(chunk)
            yield f"data: {chunk}\n\n"
    except Exception as exc:
        log.error("STREAM_ERROR  provider=%s model=%s: %s: %s",
                  body.provider, body.model, type(exc).__name__, exc)
        yield f"data: [ERROR] {exc}\n\n"
    finally:
        elapsed = time.monotonic() - t0
        tokens = len("".join(full_content).split())
        log.info("STREAM_DONE  provider=%s model=%s tokens~=%d elapsed=%.2fs",
                 body.provider, body.model, tokens, elapsed)
        if full_content:
            assistant_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content="".join(full_content),
                model=body.model,
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)

            asyncio.create_task(_bg_index_and_summarize(assistant_msg.id, conv_id))

            if final_usage is not None:
                asyncio.create_task(_bg_log_chat_usage(
                    provider=body.provider,
                    model=body.model,
                    input_tokens=final_usage.input_tokens,
                    output_tokens=final_usage.output_tokens,
                    user_id=user_id,
                    conversation_id=conv_id,
                    message_id=assistant_msg.id,
                ))

        yield "data: [DONE]\n\n"
