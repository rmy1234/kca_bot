import hashlib
import math
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Question, ReferenceQuestion, Topic, TopicEmbedding


EMBEDDING_DIMENSION = 64
DUPLICATE_THRESHOLD = 0.92
# Study-material characters for one generation request, split across its Topics so a subject-wide
# prompt plus the generated JSON still fits a local model's context window (OLLAMA_NUM_CTX).
CONTEXT_CHAR_BUDGET = 4000
MIN_TOPIC_CONTEXT_CHARS = 400
CONTEXT_CANDIDATES = 6
MIN_CONTEXT_PIECE_CHARS = 200


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


def pack_context(chunks: list[str], char_budget: int) -> list[str]:
    """Take chunks in order until the character budget is spent, truncating the chunk that crosses it."""
    packed: list[str] = []
    remaining = char_budget
    for chunk in chunks:
        if remaining < MIN_CONTEXT_PIECE_CHARS:
            break
        packed.append(chunk[:remaining])
        remaining -= len(chunk)
    return packed


async def retrieve_context(session: AsyncSession, topic: Topic, char_budget: int = CONTEXT_CHAR_BUDGET) -> list[str]:
    """Uploaded study-material excerpts classified under this Topic; the Topic summary is already in the prompt."""
    chunks = (await session.scalars(
        select(TopicEmbedding).where(
            TopicEmbedding.topic_id == topic.id,
            TopicEmbedding.source_document_id.is_not(None),
        )
    )).all()
    query_vector = embed_text(f"{topic.name} {' '.join(topic.keywords)} {topic.summary_text}")
    ranked = sorted(chunks, key=lambda item: cosine_similarity(query_vector, item.embedding), reverse=True)
    # Shuffle the most relevant excerpts so repeated generations draw on different parts of the material.
    candidates = [item.chunk_text for item in ranked[:CONTEXT_CANDIDATES]]
    random.shuffle(candidates)
    return pack_context(candidates, char_budget)


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
