from datetime import datetime
from datetime import date
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

class Base(DeclarativeBase): pass

class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    weight: Mapped[int] = mapped_column(Integer, default=20)
    domains: Mapped[list["Domain"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    source_documents: Mapped[list["SourceDocument"]] = relationship(back_populates="subject")

class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    subject: Mapped[Subject] = relationship(back_populates="domains")
    topics: Mapped[list["Topic"]] = relationship(back_populates="domain", cascade="all, delete-orphan")

class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    summary_text: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty_level: Mapped[int] = mapped_column(Integer, default=1)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_version: Mapped[str] = mapped_column(String(80), default="v1")
    domain: Mapped[Domain] = relationship(back_populates="topics")
    questions: Mapped[list["Question"]] = relationship(back_populates="topic", cascade="all, delete-orphan")
    embeddings: Mapped[list["TopicEmbedding"]] = relationship(back_populates="topic", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    exam_type: Mapped[str] = mapped_column(String(30), default="written")
    type: Mapped[str] = mapped_column(String(30), default="multiple_choice")
    question_text: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    answer_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    grading_keywords: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | None] = mapped_column(String(500))
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    quality_score: Mapped[float] = mapped_column(Float, default=1.0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model_version: Mapped[str] = mapped_column(String(80), default="mock-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    topic: Mapped[Topic] = relationship(back_populates="questions")
    answer_logs: Mapped[list["UserAnswerLog"]] = relationship(back_populates="question", cascade="all, delete-orphan")

class UserAnswerLog(Base):
    __tablename__ = "user_answer_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True, default=1)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    selected_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column()
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    time_spent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question: Mapped[Question] = relationship(back_populates="answer_logs")
    user: Mapped["User"] = relationship(back_populates="answer_logs")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    answer_logs: Mapped[list[UserAnswerLog]] = relationship(back_populates="user")
    essay_answers: Mapped[list["UserEssayAnswer"]] = relationship(back_populates="user")


class TopicEmbedding(Base):
    __tablename__ = "topic_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"), nullable=True, index=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)

    topic: Mapped[Topic] = relationship(back_populates="embeddings")
    source_document: Mapped["SourceDocument | None"] = relationship(back_populates="embeddings")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[str] = mapped_column(String(80), default="v1")
    status: Mapped[str] = mapped_column(String(30), default="처리중", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[Subject] = relationship(back_populates="source_documents")
    embeddings: Mapped[list[TopicEmbedding]] = relationship(back_populates="source_document", cascade="all, delete-orphan")
    reference_questions: Mapped[list["ReferenceQuestion"]] = relationship(back_populates="source_document", cascade="all, delete-orphan")


class ReferenceQuestion(Base):
    __tablename__ = "reference_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document: Mapped[SourceDocument] = relationship(back_populates="reference_questions")
    topic: Mapped[Topic] = relationship()


class GenerationLog(Base):
    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False, index=True)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetition_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship()
    topic: Mapped[Topic] = relationship()


class UserEssayAnswer(Base):
    __tablename__ = "user_essay_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_feedback: Mapped[dict] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[User] = relationship(back_populates="essay_answers")
    question: Mapped[Question] = relationship()
