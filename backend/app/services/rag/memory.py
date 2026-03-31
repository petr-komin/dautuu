"""Memory service — indexace zpráv, sumarizace konverzací, retrieval kontextu."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.services.rag.embeddings import embed
from app.core.config import settings

log = logging.getLogger("dautuu.memory")

# Konverzace se sumarizuje pokud je poslední zpráva starší než toto
SUMMARIZE_AFTER_IDLE = timedelta(minutes=30)

# Počet výsledků z vector search
TOP_K_MESSAGES = 5
TOP_K_SUMMARIES = 3


# ---------------------------------------------------------------------------
# Indexace zprávy
# ---------------------------------------------------------------------------

async def index_message(message_id: UUID, db: AsyncSession) -> None:
    """Vypočítá a uloží embedding pro jednu zprávu."""
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg or msg.embedding is not None:
        return  # už zaindexováno nebo nenalezeno

    try:
        msg.embedding = await embed(msg.content, db=db)
        await db.commit()
        log.info("INDEXED msg=%s role=%s", message_id, msg.role)
    except Exception as exc:
        log.error("INDEX_ERROR msg=%s: %s", message_id, exc)
        await db.rollback()


# ---------------------------------------------------------------------------
# Sumarizace konverzace
# ---------------------------------------------------------------------------

async def maybe_summarize(conversation_id: UUID, db: AsyncSession) -> None:
    """Sumarizuje konverzaci pokud je dostatečně stará a ještě nemá aktuální souhrn."""
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        return

    now = datetime.now(timezone.utc)
    idle_since = now - conv.updated_at

    # Sumarizovat jen pokud je nečinnost > threshold a souhrn je zastaralý
    if idle_since < SUMMARIZE_AFTER_IDLE:
        return
    if conv.summarized_at and conv.summarized_at >= conv.updated_at:
        return

    # Načti zprávy
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = msgs_result.scalars().all()
    if len(messages) < 3:
        return  # příliš krátká konverzace

    log.info("SUMMARIZING conv=%s (%d zpráv)", conversation_id, len(messages))

    # Sestav konverzaci jako text
    transcript = "\n".join(
        f"{m.role.upper()}: {m.content[:500]}"
        for m in messages
        if m.role in ("user", "assistant")
    )

    prompt = (
        "Napiš stručný souhrn následující konverzace v češtině nebo v jazyce konverzace. "
        "Zaměř se na klíčová fakta, rozhodnutí a informace které by mohly být užitečné v budoucích konverzacích. "
        "Max 300 slov.\n\n"
        f"{transcript}"
    )

    try:
        from app.services.llm.router import chat, ChatMessage
        resp = await chat(
            messages=[ChatMessage(role="user", content=prompt)],
            model=settings.summarization_model,
            provider=settings.summarization_provider,
            temperature=0.3,
            max_tokens=512,
        )
        summary = resp.content.strip()
        summary_emb = await embed(summary, db=db)

        conv.summary = summary
        conv.summary_embedding = summary_emb
        conv.summarized_at = now
        await db.commit()
        log.info("SUMMARIZED conv=%s summary_len=%d", conversation_id, len(summary))
    except Exception as exc:
        log.error("SUMMARIZE_ERROR conv=%s: %s", conversation_id, exc)
        await db.rollback()


# ---------------------------------------------------------------------------
# Retrieval — hledání relevantního kontextu
# ---------------------------------------------------------------------------

async def retrieve_memory(
    query: str,
    user_id: UUID,
    current_conv_id: UUID,
    db: AsyncSession,
) -> str:
    """Vrátí relevantní kontext z minulých konverzací jako text pro system prompt."""
    try:
        query_emb = await embed(query)
    except Exception as exc:
        log.error("EMBED_QUERY_ERROR: %s", exc)
        return ""

    # 1. Hledej podobné zprávy z JINÝCH konverzací
    similar_messages = await db.execute(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Conversation.id != current_conv_id,
            Message.embedding.isnot(None),
            Message.role == "assistant",
        )
        .order_by(Message.embedding.cosine_distance(query_emb))
        .limit(TOP_K_MESSAGES)
    )
    msg_rows = similar_messages.all()

    # 2. Hledej podobné souhrny konverzací
    similar_summaries = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.id != current_conv_id,
            Conversation.summary_embedding.isnot(None),
        )
        .order_by(Conversation.summary_embedding.cosine_distance(query_emb))
        .limit(TOP_K_SUMMARIES)
    )
    summary_rows = similar_summaries.scalars().all()

    if not msg_rows and not summary_rows:
        return ""

    parts: list[str] = []

    if summary_rows:
        parts.append("## Souhrny relevantních minulých konverzací")
        for conv in summary_rows:
            date = conv.created_at.strftime("%d.%m.%Y")
            parts.append(f"[{date} — {conv.title}]\n{conv.summary}")

    if msg_rows:
        parts.append("## Relevantní úryvky z minulých konverzací")
        for msg, conv in msg_rows:
            date = conv.created_at.strftime("%d.%m.%Y")
            parts.append(f"[{date} — {conv.title}]\nAsistent: {msg.content[:400]}")

    memory_block = "\n\n".join(parts)
    log.info("MEMORY retrieved %d summaries + %d messages for query '%s...'",
             len(summary_rows), len(msg_rows), query[:50])
    return memory_block
