from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Domain, GenerationLog, Question, ReferenceQuestion, ReviewSchedule, SourceDocument, Subject, Topic, TopicEmbedding, User, UserAnswerLog, UserEssayAnswer
from app.db.session import AsyncSessionLocal, engine
from app.llm import get_question_generator
from app.llm import verify_question
from app.rag import is_duplicate_question, retrieve_context, retrieve_reference_questions
from app.schemas import (
    AccuracyStat, AnswerRequest, AnswerResponse, DomainTopicsResponse,
    GenerateQuestionsRequest, QuestionResponse, StatsResponse,
    SubjectResponse, WrongNoteResponse, ReviewQueueItem,
    EssayFeedbackResponse, EssayHistoryItem, EssayQuestionResponse, EssaySubmitRequest,
    AdminTopicRequest, DocumentDetailResponse, DocumentEmbeddingResponse, ReassignEmbeddingRequest,
    ReferenceQuestionRequest, ReferenceQuestionResponse, SourceDocumentResponse,
)
from app.seed import seed_curriculum
from app.srs.sm2 import SM2State, update_sm2
from app.essay import DISCLAIMER, get_essay_llm
from app.ingestion import ALLOWED_DOC_TYPES, MAX_UPLOAD_BYTES, process_document, regenerate_summary_embeddings, reprocess_document, validate_upload

settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await seed_curriculum(session)
    yield
    await engine.dispose()

app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

async def db_session():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok"}

@app.get("/subjects", response_model=list[SubjectResponse], tags=["curriculum"])
async def list_subjects(db: AsyncSession = Depends(db_session)):
    return (await db.scalars(select(Subject).order_by(Subject.id))).all()

@app.get("/subjects/{subject_id}/topics", response_model=list[DomainTopicsResponse], tags=["curriculum"])
async def list_subject_topics(subject_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(Subject, subject_id):
        raise HTTPException(404, "Subject not found")
    result = await db.scalars(select(Domain).where(Domain.subject_id == subject_id).options(selectinload(Domain.topics)).order_by(Domain.id))
    return result.all()

@app.post("/questions/generate", response_model=list[QuestionResponse], tags=["questions"])
async def generate_questions(request: GenerateQuestionsRequest, db: AsyncSession = Depends(db_session)):
    topic = await db.get(Topic, request.topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    context = await retrieve_context(db, topic)
    references = await retrieve_reference_questions(db, topic.id)
    generated = await get_question_generator().generate(topic, request.count, [item[0] for item in context], references)
    questions = []
    for item in generated:
        valid, reason = await verify_question(item, topic)
        if not valid:
            db.add(GenerationLog(topic_id=topic.id, status="rejected", reject_reason=f"self_verification: {reason}"))
            continue
        duplicate, similarity = await is_duplicate_question(db, topic.id, item.question)
        if duplicate:
            db.add(GenerationLog(topic_id=topic.id, status="rejected", reject_reason=f"duplicate_similarity={similarity}"))
            continue
        questions.append(Question(topic_id=topic.id, question_text=item.question, choices=item.choices, answer_index=item.answer_index, explanation=item.explanation, difficulty=item.difficulty, source="mock://question-generator", model_version="mock-v1", quality_score=1.0))
        db.add(GenerationLog(topic_id=topic.id, status="accepted", reject_reason=None))
    db.add_all(questions)
    await db.commit()
    for question in questions:
        await db.refresh(question)
    return questions


@app.get("/admin/generation-logs", tags=["admin"])
async def generation_logs(limit: int = 100, db: AsyncSession = Depends(db_session)):
    if limit < 1 or limit > 500:
        raise HTTPException(422, "limit must be between 1 and 500")
    logs = (await db.scalars(select(GenerationLog).order_by(GenerationLog.created_at.desc()).limit(limit))).all()
    return [{"id": log.id, "topic_id": log.topic_id, "status": log.status, "reject_reason": log.reject_reason, "created_at": log.created_at} for log in logs]


def document_response(document: SourceDocument) -> SourceDocumentResponse:
    return SourceDocumentResponse(
        id=document.id, title=document.title, doc_type=document.doc_type,
        subject_id=document.subject_id, uploaded_at=document.uploaded_at,
        version=document.version, status=document.status, error_message=document.error_message,
    )


@app.post("/admin/topics", tags=["admin"])
async def upsert_topic(request: AdminTopicRequest, db: AsyncSession = Depends(db_session)):
    if not await db.get(Domain, request.domain_id):
        raise HTTPException(404, "Domain not found")
    topic = await db.get(Topic, request.id) if request.id else None
    if request.id and not topic:
        raise HTTPException(404, "Topic not found")
    if topic is None:
        topic = Topic(domain_id=request.domain_id, name=request.name, summary_text=request.summary_text)
        db.add(topic)
    else:
        topic.domain_id = request.domain_id
        topic.name = request.name
        topic.summary_text = request.summary_text
    topic.keywords = request.keywords
    topic.difficulty_level = request.difficulty_level
    topic.content_version = request.content_version
    topic.last_updated_at = datetime.now(timezone.utc)
    await db.flush()
    await regenerate_summary_embeddings(db, topic)
    await db.commit()
    await db.refresh(topic)
    return {"id": topic.id, "name": topic.name, "content_version": topic.content_version, "embeddings_regenerated": True}


@app.post("/admin/documents/upload", response_model=SourceDocumentResponse, tags=["admin"])
async def upload_document(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    doc_type: str = Form(...),
    subject_id: int = Form(...),
    version: str = Form("v1"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(db_session),
):
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(422, "doc_type must be one of: 이론서, 법령, 기출문제, 요약노트")
    if not await db.get(Subject, subject_id):
        raise HTTPException(404, "Subject not found")
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        suffix = validate_upload(file.filename or "", file.content_type, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    document = SourceDocument(title=title.strip(), doc_type=doc_type, subject_id=subject_id, version=version.strip() or "v1", status="처리중")
    if not document.title:
        raise HTTPException(422, "title is required")
    db.add(document)
    await db.commit()
    await db.refresh(document)
    background_tasks.add_task(process_document, document.id, payload, suffix)
    return document_response(document)


@app.get("/admin/documents", response_model=list[SourceDocumentResponse], tags=["admin"])
async def list_documents(subject_id: int | None = None, db: AsyncSession = Depends(db_session)):
    query = select(SourceDocument).order_by(SourceDocument.uploaded_at.desc())
    if subject_id is not None:
        query = query.where(SourceDocument.subject_id == subject_id)
    documents = (await db.scalars(query)).all()
    return [document_response(document) for document in documents]


@app.get("/admin/documents/{document_id}/status", response_model=DocumentDetailResponse, tags=["admin"])
async def document_status(document_id: int, db: AsyncSession = Depends(db_session)):
    document = await db.get(SourceDocument, document_id, options=[selectinload(SourceDocument.embeddings).selectinload(TopicEmbedding.topic)])
    if not document:
        raise HTTPException(404, "Document not found")
    return DocumentDetailResponse(
        **document_response(document).model_dump(),
        embeddings=[DocumentEmbeddingResponse(id=item.id, topic_id=item.topic_id, topic_name=item.topic.name, chunk_preview=item.chunk_text[:240]) for item in document.embeddings],
    )


@app.patch("/admin/documents/{document_id}/embeddings/{embedding_id}", tags=["admin"])
async def reassign_document_embedding(document_id: int, embedding_id: int, request: ReassignEmbeddingRequest, db: AsyncSession = Depends(db_session)):
    embedding = await db.get(TopicEmbedding, embedding_id)
    if not embedding or embedding.source_document_id != document_id:
        raise HTTPException(404, "Document chunk not found")
    topic = await db.get(Topic, request.topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    document = await db.get(SourceDocument, document_id)
    topic_domain = await db.get(Domain, topic.domain_id)
    if topic_domain.subject_id != document.subject_id:
        raise HTTPException(422, "Topic must belong to the document subject")
    embedding.topic_id = topic.id
    await db.commit()
    return {"id": embedding.id, "topic_id": embedding.topic_id, "reassigned": True}


@app.post("/admin/documents/{document_id}/reprocess", response_model=SourceDocumentResponse, tags=["admin"])
async def reprocess_source_document(document_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(db_session)):
    document = await db.get(SourceDocument, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    document.status = "처리중"
    document.error_message = None
    await db.commit()
    await db.refresh(document)
    background_tasks.add_task(reprocess_document, document.id)
    return document_response(document)


@app.delete("/admin/documents/{document_id}", tags=["admin"])
async def delete_source_document(document_id: int, db: AsyncSession = Depends(db_session)):
    document = await db.get(SourceDocument, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    await db.delete(document)
    await db.commit()
    return {"id": document_id, "deleted": True}


@app.get("/admin/topics/{topic_id}/documents", response_model=list[SourceDocumentResponse], tags=["admin"])
async def topic_source_documents(topic_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(Topic, topic_id):
        raise HTTPException(404, "Topic not found")
    documents = (await db.scalars(
        select(SourceDocument).join(TopicEmbedding).where(TopicEmbedding.topic_id == topic_id).distinct()
    )).all()
    return [document_response(document) for document in documents]


@app.post("/admin/reference-questions", response_model=ReferenceQuestionResponse, tags=["admin"])
async def create_reference_question(request: ReferenceQuestionRequest, db: AsyncSession = Depends(db_session)):
    document = await db.get(SourceDocument, request.source_document_id)
    topic = await db.get(Topic, request.topic_id)
    if not document or not topic:
        raise HTTPException(404, "Source document or Topic not found")
    topic_domain = await db.get(Domain, topic.domain_id)
    if topic_domain.subject_id != document.subject_id:
        raise HTTPException(422, "Topic must belong to the source document subject")
    reference = ReferenceQuestion(**request.model_dump())
    db.add(reference)
    await db.commit()
    await db.refresh(reference)
    return reference

@app.get("/questions/pool", response_model=list[QuestionResponse], tags=["questions"])
async def question_pool(topic_id: int, limit: int = 10, user_id: int = 1, db: AsyncSession = Depends(db_session)):
    if limit < 1 or limit > 50:
        raise HTTPException(422, "limit must be between 1 and 50")
    if not await db.get(Topic, topic_id):
        raise HTTPException(404, "Topic not found")
    questions = (await db.scalars(select(Question).where(Question.topic_id == topic_id).order_by(Question.created_at.desc()).limit(200))).all()
    answered_ids = set(await db.scalars(select(UserAnswerLog.question_id).where(UserAnswerLog.user_id == user_id, UserAnswerLog.question_id.in_([q.id for q in questions]))))
    questions.sort(key=lambda question: (question.id in answered_ids, question.created_at), reverse=False)
    return questions[:limit]

@app.post("/questions/{question_id}/answer", response_model=AnswerResponse, tags=["questions"])
async def answer_question(question_id: int, request: AnswerRequest, db: AsyncSession = Depends(db_session)):
    question = await db.get(Question, question_id)
    if not question:
        raise HTTPException(404, "Question not found")
    if not await db.get(User, request.user_id):
        raise HTTPException(404, "User not found")
    is_correct = request.selected_index == question.answer_index
    db.add(UserAnswerLog(user_id=request.user_id, question_id=question.id, selected_index=request.selected_index, is_correct=is_correct, time_spent=request.time_spent))
    now = datetime.now(timezone.utc)
    schedule = await db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == request.user_id, ReviewSchedule.topic_id == question.topic_id))
    current = SM2State(ease_factor=schedule.ease_factor if schedule else 2.5, interval_days=schedule.interval_days if schedule else 0, repetition_count=schedule.repetition_count if schedule else 0)
    next_state, next_review = update_sm2(current, 4 if is_correct else 2, now)
    if schedule is None:
        schedule = ReviewSchedule(user_id=request.user_id, topic_id=question.topic_id)
        db.add(schedule)
    schedule.ease_factor = next_state.ease_factor
    schedule.interval_days = next_state.interval_days
    schedule.repetition_count = next_state.repetition_count
    schedule.last_reviewed_at = now
    schedule.next_review_at = next_review
    await db.commit()
    return AnswerResponse(question_id=question.id, selected_index=request.selected_index, correct_index=question.answer_index, is_correct=is_correct, explanation=question.explanation)

@app.get("/users/{user_id}/wrong-notes", response_model=list[WrongNoteResponse], tags=["users"])
async def wrong_notes(user_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(User, user_id):
        raise HTTPException(404, "User not found")
    logs = (await db.scalars(select(UserAnswerLog).where(UserAnswerLog.user_id == user_id, UserAnswerLog.is_correct.is_(False)).options(selectinload(UserAnswerLog.question).selectinload(Question.topic)) .order_by(UserAnswerLog.answered_at.desc()))).all()
    return [WrongNoteResponse(question_id=log.question.id, question_text=log.question.question_text, choices=log.question.choices, selected_index=log.selected_index, answered_at=log.answered_at, topic_id=log.question.topic.id, topic_name=log.question.topic.name, summary_text=log.question.topic.summary_text) for log in logs]

@app.post("/questions/{question_id}/regenerate-similar", response_model=list[QuestionResponse], tags=["questions"])
async def regenerate_similar(question_id: int, db: AsyncSession = Depends(db_session)):
    question = await db.get(Question, question_id, options=[selectinload(Question.topic)])
    if not question:
        raise HTTPException(404, "Question not found")
    generated = await get_question_generator().generate(question.topic, 1)
    questions = [Question(topic_id=question.topic_id, question_text=item.question, choices=item.choices, answer_index=item.answer_index, explanation=item.explanation, difficulty=item.difficulty, source=f"mock://similar-to/{question_id}", model_version="mock-v1", quality_score=1.0) for item in generated]
    db.add_all(questions)
    await db.commit()
    for item in questions:
        await db.refresh(item)
    return questions

@app.get("/users/{user_id}/stats", response_model=StatsResponse, tags=["users"])
async def user_stats(user_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(User, user_id):
        raise HTTPException(404, "User not found")
    logs = (await db.scalars(select(UserAnswerLog).where(UserAnswerLog.user_id == user_id).options(selectinload(UserAnswerLog.question).selectinload(Question.topic).selectinload(Topic.domain).selectinload(Domain.subject)))).all()
    def aggregate(items, name_getter):
        grouped = {}
        for log in items:
            name = name_getter(log)
            total, correct = grouped.get(name, (0, 0))
            grouped[name] = (total + 1, correct + int(log.is_correct))
        return [AccuracyStat(name=name, total=total, correct=correct, accuracy=round(correct / total * 100, 1)) for name, (total, correct) in grouped.items()]
    subject_stats = aggregate(logs, lambda log: log.question.topic.domain.subject.name)
    domain_stats = aggregate(logs, lambda log: log.question.topic.domain.name)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    def is_recent(log):
        if not log.answered_at:
            return False
        answered_at = log.answered_at
        if answered_at.tzinfo is None:
            answered_at = answered_at.replace(tzinfo=timezone.utc)
        return answered_at >= since
    recent = sum(1 for log in logs if is_recent(log))
    weak = sorted([item for item in domain_stats if item.total > 0], key=lambda item: (item.accuracy, -item.total))[:3]
    return StatsResponse(subject_stats=subject_stats, domain_stats=domain_stats, recent_7_days_count=recent, weak_domains=weak)

@app.post("/questions/{question_id}/report", tags=["questions"])
async def report_question(question_id: int, db: AsyncSession = Depends(db_session)):
    question = await db.get(Question, question_id)
    if not question:
        raise HTTPException(404, "Question not found")
    question.quality_score = max(0.0, round(question.quality_score - 0.1, 2))
    await db.commit()
    return {"question_id": question.id, "quality_score": question.quality_score, "reported": True}

@app.get("/users/{user_id}/review-queue", response_model=list[ReviewQueueItem], tags=["users"])
async def review_queue(user_id: int, limit: int = 3, db: AsyncSession = Depends(db_session)):
    if not await db.get(User, user_id):
        raise HTTPException(404, "User not found")
    if limit < 1 or limit > 50:
        raise HTTPException(422, "limit must be between 1 and 50")
    now = datetime.now(timezone.utc)
    schedules = (await db.scalars(
        select(ReviewSchedule)
        .where(ReviewSchedule.user_id == user_id, ReviewSchedule.next_review_at <= now)
        .options(selectinload(ReviewSchedule.topic).selectinload(Topic.domain).selectinload(Domain.subject))
        .order_by(ReviewSchedule.next_review_at)
    )).all()
    items = []
    for schedule in schedules[:limit]:
        due = schedule.next_review_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        overdue = max(0, (now.date() - due.date()).days)
        items.append(ReviewQueueItem(
            schedule_id=schedule.id,
            topic_id=schedule.topic_id,
            topic_name=schedule.topic.name,
            domain_name=schedule.topic.domain.name,
            subject_name=schedule.topic.domain.subject.name,
            next_review_at=schedule.next_review_at,
            overdue_days=overdue,
            interval_days=schedule.interval_days,
            repetition_count=schedule.repetition_count,
        ))
    return items
@app.get("/essay-questions/generate", response_model=EssayQuestionResponse, tags=["essay"])
async def generate_essay_question(topic_id: int, db: AsyncSession = Depends(db_session)):
    topic = await db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    generated = await get_essay_llm().generate(topic)
    question = Question(
        topic_id=topic.id,
        exam_type="실기",
        type="essay",
        question_text=generated.question,
        choices=None,
        answer_index=None,
        explanation=None,
        model_answer=generated.model_answer,
        grading_keywords=generated.grading_keywords,
        difficulty=generated.difficulty,
        source="mock://essay-generator",
        model_version="mock-essay-v1",
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question


@app.post("/essay-questions/{question_id}/submit", response_model=EssayFeedbackResponse, tags=["essay"])
async def submit_essay(question_id: int, request: EssaySubmitRequest, db: AsyncSession = Depends(db_session)):
    question = await db.get(Question, question_id)
    if not question or question.exam_type != "실기":
        raise HTTPException(404, "Essay question not found")
    if not await db.get(User, request.user_id):
        raise HTTPException(404, "User not found")
    feedback = await get_essay_llm().grade(question, request.answer_text)
    feedback_payload = {
        "covered_keywords": feedback.covered_keywords,
        "missing_keywords": feedback.missing_keywords,
        "score": feedback.score,
        "feedback_text": feedback.feedback_text,
        "improvement_suggestion": feedback.improvement_suggestion,
        "disclaimer": DISCLAIMER,
    }
    essay_answer = UserEssayAnswer(
        user_id=request.user_id,
        question_id=question.id,
        answer_text=request.answer_text,
        ai_feedback=feedback_payload,
        score=feedback.score,
    )
    db.add(essay_answer)
    await db.commit()
    await db.refresh(essay_answer)
    return EssayFeedbackResponse(
        essay_answer_id=essay_answer.id,
        question_id=question.id,
        score=feedback.score,
        covered_keywords=feedback.covered_keywords,
        missing_keywords=feedback.missing_keywords,
        feedback_text=feedback.feedback_text,
        improvement_suggestion=feedback.improvement_suggestion,
        disclaimer=DISCLAIMER,
    )


@app.get("/users/{user_id}/essay-history", response_model=list[EssayHistoryItem], tags=["essay"])
async def essay_history(user_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(User, user_id):
        raise HTTPException(404, "User not found")
    answers = (await db.scalars(
        select(UserEssayAnswer)
        .where(UserEssayAnswer.user_id == user_id)
        .options(selectinload(UserEssayAnswer.question))
        .order_by(UserEssayAnswer.created_at.desc())
    )).all()
    return [
        EssayHistoryItem(
            id=answer.id,
            question_id=answer.question_id,
            question_text=answer.question.question_text,
            answer_text=answer.answer_text,
            ai_feedback=answer.ai_feedback,
            score=answer.score,
            created_at=answer.created_at,
        )
        for answer in answers
    ]
