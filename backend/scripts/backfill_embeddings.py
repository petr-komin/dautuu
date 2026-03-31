"""One-off script: backfill embeddings for messages that don't have them yet."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("backfill")


async def main():
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models import Message
    from app.services.rag.embeddings import embed

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message).where(Message.embedding.is_(None))
        )
        messages = result.scalars().all()
        log.info("Found %d messages without embeddings", len(messages))

        ok = 0
        fail = 0
        for msg in messages:
            if not msg.content or not msg.content.strip():
                log.warning("Skipping empty message %s", msg.id)
                continue
            try:
                msg.embedding = await embed(msg.content)
                ok += 1
                log.info("Indexed %s (%s) role=%s", msg.id, msg.content[:40], msg.role)
            except Exception as exc:
                fail += 1
                log.error("Failed %s: %s", msg.id, exc)

        await db.commit()
        log.info("Done — indexed=%d failed=%d", ok, fail)


if __name__ == "__main__":
    asyncio.run(main())
