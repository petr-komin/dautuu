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
from app.db.models import User, Conversation, Message
from app.services.llm.router import chat, stream_with_usage, ChatMessage, Provider
from app.services.rag.memory import index_message, maybe_summarize, retrieve_memory
from app.services.usage.logger import log_chat_usage

log = logging.getLogger("dautuu.chat")

router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
DEFAULT_PROVIDER: Provider = "together"

SYSTEM_PROMPT = (
    "Jsi osobní AI asistent. Jsi přátelský, přesný a užitečný. "
    "Pokud nevíš odpověď, řekni to upřímně."
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    title: str = "Nová konverzace"


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str
    model: str = DEFAULT_MODEL
    provider: Provider = DEFAULT_PROVIDER
    stream: bool = True


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
# Conversations
# ---------------------------------------------------------------------------

@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=current_user.id, title=body.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


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
        conv = Conversation(user_id=current_user.id, title=body.message[:60])
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

    # Načti paměť z minulých konverzací
    memory = await retrieve_memory(
        query=body.message,
        user_id=current_user.id,
        current_conv_id=conv.id,
        db=db,
    )

    # Sestavíme historii zpráv pro LLM
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(40)
    )
    history = history_result.scalars().all()

    # System prompt + volitelná paměť z minulých konverzací
    system_content = SYSTEM_PROMPT
    if memory:
        system_content += (
            "\n\n---\nNíže jsou relevantní informace z předchozích konverzací s uživatelem. "
            "Využij je pokud jsou užitečné pro odpověď, ale nezmiňuj explicitně že je čteš.\n\n"
            + memory
        )

    llm_messages = [ChatMessage(role="system", content=system_content)]
    for msg in history:
        llm_messages.append(ChatMessage(role=msg.role, content=msg.content))  # type: ignore[arg-type]

    # Streaming odpověď
    if body.stream:
        log.info("STREAM  user=%s conv=%s provider=%s model=%s memory=%s",
                 current_user.id, conv.id, body.provider, body.model, bool(memory))
        return StreamingResponse(
            _stream_and_save(llm_messages, body, conv.id, current_user.id, db),
            media_type="text/event-stream",
            headers={
                "X-Conversation-Id": str(conv.id),
                "Cache-Control": "no-cache",
            },
        )

    # Blokující odpověď
    response = await chat(
        messages=llm_messages,
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

    # Loguj usage pro blokující odpověď
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
    """Zaloguje usage v samostatné DB session (background task)."""
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


async def _stream_and_save(
    llm_messages, body: ChatRequest, conv_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession,
):
    """Generator pro SSE streaming + uložení + indexace na pozadí."""
    full_content = []
    t0 = time.monotonic()
    first_token = True
    final_usage = None
    try:
        async for chunk, usage_info in stream_with_usage(
            messages=llm_messages,
            model=body.model,
            provider=body.provider,
        ):
            if usage_info is not None:
                # Poslední yield s prázdným chunkem a usage info
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

            # Indexace + případná sumarizace na pozadí
            asyncio.create_task(_bg_index_and_summarize(assistant_msg.id, conv_id))

            # Loguj usage na pozadí
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
