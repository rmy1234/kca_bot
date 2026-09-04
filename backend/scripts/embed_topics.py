import asyncio

from sqlalchemy import select

from app.db.models import Topic
from app.db.session import AsyncSessionLocal, engine
from app.rag import ensure_topic_embeddings


async def main():
    async with AsyncSessionLocal() as session:
        topics = (await session.scalars(select(Topic).order_by(Topic.id))).all()
        for topic in topics:
            await ensure_topic_embeddings(session, topic)
    await engine.dispose()
    print(f"Embedded {len(topics)} topics.")


if __name__ == "__main__":
    asyncio.run(main())

