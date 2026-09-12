from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import math
import random
from typing import AsyncIterator, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import create_access_token, get_current_user, hash_password, require_admin, verify_password
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Domain, GenerationLog, Question, ReferenceQuestion, ReviewSchedule, SourceDocument, Subject, Topic, TopicEmbedding, User, UserAnswerLog, UserEssayAnswer
from app.db.session import AsyncSessionLocal, engine
from app.llm import LLMUnavailableError, QuestionRequest, get_question_generator, llm_backend, llm_status, model_label, verify_questions
from app.rag import is_duplicate_question, retrieve_context, retrieve_reference_questions
from app.schemas import (
    AccuracyStat, AnswerRequest, AnswerResponse, DomainTopicsResponse,
    GenerateQuestionsRequest, GenerateQuestionsResponse, LLMStatusResponse, PoolQuestionResponse, QuestionResponse, StatsResponse,
    SubjectResponse, WrongNoteResponse, ReviewQueueItem,
    EssayFeedbackResponse, EssayHistoryItem, EssayQuestionResponse, EssaySubmitRequest,
    AdminTopicRequest, DocumentDetailResponse, DocumentEmbeddingResponse, ReassignEmbeddingRequest,
    ReferenceQuestionRequest, ReferenceQuestionResponse, SourceDocumentResponse,
    LoginRequest, RegisterRequest, TokenResponse, UserResponse,
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
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

async def db_session():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok"}

@app.post("/auth/register", response_model=TokenResponse, tags=["auth"])
async def register(request: RegisterRequest, db: AsyncSession = Depends(db_session)):
    if await db.scalar(select(User).where(User.email == request.email)):
        raise HTTPException(409, "Email already registered")
    user = User(name=request.name, email=request.email, password_hash=hash_password(request.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))

@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(request: LoginRequest, db: AsyncSession = Depends(db_session)):
    user = await db.scalar(select(User).where(User.email == request.email))
    if not user or not user.password_hash or not verify_password(request.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))

@app.get("/auth/me", response_model=UserResponse, tags=["auth"])
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/subjects", response_model=list[SubjectResponse], tags=["curriculum"])
async def list_subjects(db: AsyncSession = Depends(db_session)):
    return (await db.scalars(select(Subject).order_by(Subject.id))).all()

@app.get("/subjects/{subject_id}/topics", response_model=list[DomainTopicsResponse], tags=["curriculum"])
async def list_subject_topics(subject_id: int, db: AsyncSession = Depends(db_session)):
    if not await db.get(Subject, subject_id):
        raise HTTPException(404, "Subject not found")
    result = await db.scalars(select(Domain).where(Domain.subject_id == subject_id).options(selectinload(Domain.topics)).order_by(Domain.id))
    return result.all()

def allocate_question_counts(topics: list[Topic], count: int) -> list[tuple[Topic, int]]:
    """Spread count over randomly ordered topics so a subject-wide set covers as many topics as possible."""
    shuffled = random.sample(topics, len(topics))
    counts = Counter(shuffled[index % len(shuffled)].id for index in range(count))
    return [(topic, counts[topic.id]) for topic in shuffled if counts[topic.id]]

@app.get("/llm/status", response_model=LLMStatusResponse, tags=["llm"])
async def get_llm_status(current_user: User = Depends(get_current_user)):
    return llm_status()

def llm_unavailable(exc: LLMUnavailableError) -> HTTPException:
    if exc.user_message:
        return HTTPException(exc.code, exc.user_message)
    if exc.code == 429:
        return HTTPException(429, f"Gemini 무료 요청 한도(분당 요청 수)를 초과했습니다. 약 {math.ceil(exc.retry_after)}초 후 다시 시도하세요.")
    return HTTPException(503, "Gemini 모델에 요청이 몰려 일시적으로 응답하지 못했습니다. 잠시 후 다시 시도하세요.")

@app.post("/questions/generate", response_model=GenerateQuestionsResponse, tags=["questions"])
async def generate_questions(request: GenerateQuestionsRequest, db: AsyncSession = Depends(db_session)):
    if request.subject_id is not None:
        if not await db.get(Subject, request.subject_id):
            raise HTTPException(404, "Subject not found")
        topics = (await db.scalars(select(Topic).join(Domain).where(Domain.subject_id == request.subject_id))).all()
        if not topics:
            raise HTTPException(404, "Subject has no topics")
        plan = allocate_question_counts(list(topics), request.count)
    else:
        topic = await db.get(Topic, request.topic_id)
        if not topic:
            raise HTTPException(404, "Topic not found")
        plan = [(topic, request.count)]
    requests = []
    for topic, count in plan:
        context = await retrieve_context(db, topic)
        references = await retrieve_reference_questions(db, topic.id)
        requests.append(QuestionRequest(topic=topic, count=count, context=[item[0] for item in context], references=references))
    # One generation call and one verification call per request, whatever the count, to fit the free-tier rate limit.
    try:
        generated = await get_question_generator().generate(requests)
        # Captured now: a later verification call may switch to the fallback model.
        generation_model = model_label()
    except RuntimeError as exc:
        for item in requests:
            db.add(GenerationLog(topic_id=item.topic.id, status="rejected", reject_reason=f"generation_failed: {exc}"[:1000]))
        await db.commit()
        if isinstance(exc, LLMUnavailableError):
            raise llm_unavailable(exc) from exc
        raise HTTPException(502, "문제 생성에 실패했습니다. 잠시 후 다시 시도하세요.") from exc
    topics_by_id = {item.topic.id: item.topic for item in requests}
    verdicts = await verify_questions([(topics_by_id[item.topic_id], item) for item in generated])
    questions, rejected, unverified = [], 0, 0
    for item, (verdict, reason) in zip(generated, verdicts):
        if verdict == "invalid":
            rejected += 1
            db.add(GenerationLog(topic_id=item.topic_id, status="rejected", reject_reason=f"self_verification: {reason}"[:1000]))
            continue
        # Earlier questions in this batch are autoflushed before the query, so in-batch duplicates are caught too.
        duplicate, similarity = await is_duplicate_question(db, item.topic_id, item.question)
        if duplicate:
            rejected += 1
            db.add(GenerationLog(topic_id=item.topic_id, status="rejected", reject_reason=f"duplicate_similarity={similarity}"))
            continue
        # A failed verification call keeps the question, flagged so the user can double-check it.
        verification_status = "verified" if verdict == "valid" else "unverified"
        unverified += verification_status == "unverified"
        question = Question(topic_id=item.topic_id, question_text=item.question, choices=item.choices, answer_index=item.answer_index, explanation=item.explanation, difficulty=item.difficulty, source=f"{llm_backend()}://question-generator", model_version=generation_model, quality_score=1.0, verification_status=verification_status)
        db.add(question)
        questions.append(question)
        db.add(GenerationLog(topic_id=item.topic_id, status="accepted" if verification_status == "verified" else "unverified", reject_reason=reason[:1000] if reason else None))
    await db.commit()
    for question in questions:
        await db.refresh(question)
    return GenerateQuestionsResponse(questions=[QuestionResponse.model_validate(question) for question in questions], requested=request.count, rejected=rejected, unverified=unverified)


@app.get("/admin/generation-logs", tags=["admin"])
async def generation_logs(limit: int = 100, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
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
async def upsert_topic(request: AdminTopicRequest, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
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
    _admin: User = Depends(require_admin),
):
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(422, "doc_type must be one of: " + ", ".join(ALLOWED_DOC_TYPES))
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
async def list_documents(subject_id: int | None = None, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
    query = select(SourceDocument).order_by(SourceDocument.uploaded_at.desc())
    if subject_id is not None:
        query = query.where(SourceDocument.subject_id == subject_id)
    documents = (await db.scalars(query)).all()
    return [document_response(document) for document in documents]


@app.get("/admin/documents/{document_id}/status", response_model=DocumentDetailResponse, tags=["admin"])
async def document_status(document_id: int, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
    document = await db.get(SourceDocument, document_id, options=[selectinload(SourceDocument.embeddings).selectinload(TopicEmbedding.topic)])
    if not document:
        raise HTTPException(404, "Document not found")
    return DocumentDetailResponse(
        **document_response(document).model_dump(),
        embeddings=[DocumentEmbeddingResponse(id=item.id, topic_id=item.topic_id, topic_name=item.topic.name, chunk_preview=item.chunk_text[:240]) for item in document.embeddings],
    )


@app.patch("/admin/documents/{document_id}/embeddings/{embedding_id}", tags=["admin"])
async def reassign_document_embedding(document_id: int, embedding_id: int, request: ReassignEmbeddingRequest, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
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
async def reprocess_source_document(document_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
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
async def delete_source_document(document_id: int, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
    document = await db.get(SourceDocument, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    await db.delete(document)
    await db.commit()
    return {"id": document_id, "deleted": True}


@app.get("/admin/topics/{topic_id}/documents", response_model=list[SourceDocumentResponse], tags=["admin"])
async def topic_source_documents(topic_id: int, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
    if not await db.get(Topic, topic_id):
        raise HTTPException(404, "Topic not found")
    documents = (await db.scalars(
        select(SourceDocument).join(TopicEmbedding).where(TopicEmbedding.topic_id == topic_id).distinct()
    )).all()
    return [document_response(document) for document in documents]


@app.post("/admin/reference-questions", response_model=ReferenceQuestionResponse, tags=["admin"])
async def create_reference_question(request: ReferenceQuestionRequest, db: AsyncSession = Depends(db_session), _admin: User = Depends(require_admin)):
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

PoolStatus = Literal["all", "unanswered", "wrong"]

def select_pool_questions(questions: list[Question], last_results: dict[int, bool], status: PoolStatus, limit: int) -> list[Question]:
    """Pick saved questions by the user's latest attempt: unanswered, last answered wrong, or all (unanswered first)."""
    if status == "unanswered":
        picked = [question for question in questions if question.id not in last_results]
    elif status == "wrong":
        picked = [question for question in questions if last_results.get(question.id) is False]
    else:
        picked = list(questions)
    random.shuffle(picked)
    if status == "all":
        picked.sort(key=lambda question: question.id in last_results)
    return picked[:limit]

@app.get("/questions/pool", response_model=list[PoolQuestionResponse], tags=["questions"])
async def question_pool(topic_id: int | None = None, subject_id: int | None = None, status: PoolStatus = "all", limit: int = 10, db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    if limit < 1 or limit > 50:
        raise HTTPException(422, "limit must be between 1 and 50")
    if (topic_id is None) == (subject_id is None):
        raise HTTPException(422, "topic_id와 subject_id 중 하나만 지정하세요.")
    # Essay questions have no choices, so only multiple-choice questions can be re-solved here.
    query = select(Question).where(Question.type == "multiple_choice")
    if subject_id is not None:
        if not await db.get(Subject, subject_id):
            raise HTTPException(404, "Subject not found")
        query = query.join(Topic).join(Domain).where(Domain.subject_id == subject_id)
    else:
        if not await db.get(Topic, topic_id):
            raise HTTPException(404, "Topic not found")
        query = query.where(Question.topic_id == topic_id)
    questions = (await db.scalars(query)).all()
    attempts = (await db.execute(
        select(UserAnswerLog.question_id, UserAnswerLog.is_correct)
        .where(UserAnswerLog.user_id == current_user.id, UserAnswerLog.question_id.in_([question.id for question in questions]))
        .order_by(UserAnswerLog.id)
    )).all()
    # Later attempts overwrite earlier ones, leaving each question's latest result.
    last_results = {question_id: is_correct for question_id, is_correct in attempts}
    picked = select_pool_questions(list(questions), last_results, status, limit)
    return [PoolQuestionResponse(**QuestionResponse.model_validate(question).model_dump(), last_is_correct=last_results.get(question.id)) for question in picked]

@app.post("/questions/{question_id}/answer", response_model=AnswerResponse, tags=["questions"])
async def answer_question(question_id: int, request: AnswerRequest, db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    question = await db.get(Question, question_id)
    if not question:
        raise HTTPException(404, "Question not found")
    is_correct = request.selected_index == question.answer_index
    db.add(UserAnswerLog(user_id=current_user.id, question_id=question.id, selected_index=request.selected_index, is_correct=is_correct, time_spent=request.time_spent))
    now = datetime.now(timezone.utc)
    schedule = await db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id, ReviewSchedule.topic_id == question.topic_id))
    current = SM2State(ease_factor=schedule.ease_factor if schedule else 2.5, interval_days=schedule.interval_days if schedule else 0, repetition_count=schedule.repetition_count if schedule else 0)
    next_state, next_review = update_sm2(current, 4 if is_correct else 2, now)
    if schedule is None:
        schedule = ReviewSchedule(user_id=current_user.id, topic_id=question.topic_id)
        db.add(schedule)
    schedule.ease_factor = next_state.ease_factor
    schedule.interval_days = next_state.interval_days
    schedule.repetition_count = next_state.repetition_count
    schedule.last_reviewed_at = now
    schedule.next_review_at = next_review
    await db.commit()
    return AnswerResponse(question_id=question.id, selected_index=request.selected_index, correct_index=question.answer_index, is_correct=is_correct, explanation=question.explanation)

@app.get("/users/me/wrong-notes", response_model=list[WrongNoteResponse], tags=["users"])
async def wrong_notes(db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    logs = (await db.scalars(select(UserAnswerLog).where(UserAnswerLog.user_id == current_user.id, UserAnswerLog.is_correct.is_(False)).options(selectinload(UserAnswerLog.question).selectinload(Question.topic)) .order_by(UserAnswerLog.answered_at.desc()))).all()
    return [WrongNoteResponse(question_id=log.question.id, question_text=log.question.question_text, choices=log.question.choices, selected_index=log.selected_index, answered_at=log.answered_at, topic_id=log.question.topic.id, topic_name=log.question.topic.name, summary_text=log.question.topic.summary_text) for log in logs]

@app.post("/questions/{question_id}/regenerate-similar", response_model=list[QuestionResponse], tags=["questions"])
async def regenerate_similar(question_id: int, db: AsyncSession = Depends(db_session)):
    question = await db.get(Question, question_id, options=[selectinload(Question.topic)])
    if not question:
        raise HTTPException(404, "Question not found")
    try:
        generated = await get_question_generator().generate([QuestionRequest(topic=question.topic, count=1)])
        generation_model = model_label()
    except LLMUnavailableError as exc:
        raise llm_unavailable(exc) from exc
    # Similar questions skip AI verification to save quota, so they are flagged as unverified.
    questions = [Question(topic_id=question.topic_id, question_text=item.question, choices=item.choices, answer_index=item.answer_index, explanation=item.explanation, difficulty=item.difficulty, source=f"{llm_backend()}://similar-to/{question_id}", model_version=generation_model, quality_score=1.0, verification_status="unverified") for item in generated]
    db.add_all(questions)
    await db.commit()
    for item in questions:
        await db.refresh(item)
    return questions

def first_attempts(logs: list[UserAnswerLog]) -> list[UserAnswerLog]:
    """Keep each question's first attempt so re-solving saved or wrong questions never changes accuracy. Expects logs in id order."""
    seen: set[int] = set()
    firsts = []
    for log in logs:
        if log.question_id not in seen:
            seen.add(log.question_id)
            firsts.append(log)
    return firsts

@app.get("/users/me/stats", response_model=StatsResponse, tags=["users"])
async def user_stats(db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    logs = (await db.scalars(select(UserAnswerLog).where(UserAnswerLog.user_id == current_user.id).options(selectinload(UserAnswerLog.question).selectinload(Question.topic).selectinload(Topic.domain).selectinload(Domain.subject)).order_by(UserAnswerLog.id))).all()
    def aggregate(items, name_getter):
        grouped = {}
        for log in items:
            name = name_getter(log)
            total, correct = grouped.get(name, (0, 0))
            grouped[name] = (total + 1, correct + int(log.is_correct))
        return [AccuracyStat(name=name, total=total, correct=correct, accuracy=round(correct / total * 100, 1)) for name, (total, correct) in grouped.items()]
    scored = first_attempts(list(logs))
    subject_stats = aggregate(scored, lambda log: log.question.topic.domain.subject.name)
    domain_stats = aggregate(scored, lambda log: log.question.topic.domain.name)
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

@app.get("/users/me/review-queue", response_model=list[ReviewQueueItem], tags=["users"])
async def review_queue(limit: int = 3, db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    if limit < 1 or limit > 50:
        raise HTTPException(422, "limit must be between 1 and 50")
    now = datetime.now(timezone.utc)
    schedules = (await db.scalars(
        select(ReviewSchedule)
        .where(ReviewSchedule.user_id == current_user.id, ReviewSchedule.next_review_at <= now)
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
    try:
        generated = await get_essay_llm().generate(topic)
        generation_model = model_label()
    except LLMUnavailableError as exc:
        raise llm_unavailable(exc) from exc
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
        source=f"{llm_backend()}://essay-generator",
        model_version=generation_model,
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question


@app.post("/essay-questions/{question_id}/submit", response_model=EssayFeedbackResponse, tags=["essay"])
async def submit_essay(question_id: int, request: EssaySubmitRequest, db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    question = await db.get(Question, question_id)
    if not question or question.exam_type != "실기":
        raise HTTPException(404, "Essay question not found")
    try:
        feedback = await get_essay_llm().grade(question, request.answer_text)
    except LLMUnavailableError as exc:
        raise llm_unavailable(exc) from exc
    feedback_payload = {
        "covered_keywords": feedback.covered_keywords,
        "missing_keywords": feedback.missing_keywords,
        "score": feedback.score,
        "feedback_text": feedback.feedback_text,
        "improvement_suggestion": feedback.improvement_suggestion,
        "disclaimer": DISCLAIMER,
    }
    essay_answer = UserEssayAnswer(
        user_id=current_user.id,
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


@app.get("/users/me/essay-history", response_model=list[EssayHistoryItem], tags=["essay"])
async def essay_history(db: AsyncSession = Depends(db_session), current_user: User = Depends(get_current_user)):
    answers = (await db.scalars(
        select(UserEssayAnswer)
        .where(UserEssayAnswer.user_id == current_user.id)
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
