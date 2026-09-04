import hashlib
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Question, ReferenceQuestion, Topic, TopicEmbedding


EMBEDDING_DIMENSION = 64
TOP_K = 3
DUPLICATE_THRESHOLD = 0.92


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMENSION
        vector[index] += 1.0 if digest[2] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 8) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def topic_chunks(topic: Topic) -> list[str]:
    text = topic.summary_text.strip()
    if not text:
        return []
    sentences = [part.strip() for part in text.replace("。", ".").split(".") if part.strip()]
    return sentences or [text]


async def ensure_topic_embeddings(session: AsyncSession, topic: Topic) -> list[TopicEmbedding]:
    existing = (await session.scalars(
        select(TopicEmbedding).where(
            TopicEmbedding.topic_id == topic.id,
            TopicEmbedding.source_document_id.is_(None),
        )
    )).all()
    if existing:
        return list(existing)
    embeddings = [
        TopicEmbedding(topic_id=topic.id, chunk_text=chunk, embedding=embed_text(chunk))
        for chunk in topic_chunks(topic)
    ]
    session.add_all(embeddings)
    await session.commit()
    return embeddings


async def retrieve_context(session: AsyncSession, topic: Topic, top_k: int = TOP_K) -> list[tuple[str, float]]:
    embeddings = await ensure_topic_embeddings(session, topic)
    query_vector = embed_text(f"{topic.name} {' '.join(topic.keywords)} {topic.summary_text}")
    ranked = sorted(
        ((item.chunk_text, cosine_similarity(query_vector, item.embedding)) for item in embeddings),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:top_k]


async def is_duplicate_question(session: AsyncSession, topic_id: int, question_text: str) -> tuple[bool, float]:
    existing = (await session.scalars(select(Question).where(Question.topic_id == topic_id))).all()
    if not existing:
        return False, 0.0
    candidate_vector = embed_text(question_text)
    highest = max(cosine_similarity(candidate_vector, embed_text(item.question_text)) for item in existing)
    return highest >= DUPLICATE_THRESHOLD, round(highest, 4)


async def retrieve_reference_questions(session: AsyncSession, topic_id: int, limit: int = 3) -> list[str]:
    """Return style references only; callers must never present these as generated questions."""
    references = (await session.scalars(
        select(ReferenceQuestion)
        .where(ReferenceQuestion.topic_id == topic_id)
        .order_by(ReferenceQuestion.id.desc())
        .limit(limit)
    )).all()
    return [item.original_text for item in references]
