from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    weight: int

class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    summary_text: str
    keywords: list[str]
    difficulty_level: int

class DomainTopicsResponse(BaseModel):
    id: int
    name: str
    topics: list[TopicResponse]

class GenerateQuestionsRequest(BaseModel):
    topic_id: int
    count: int = Field(1, ge=1, le=10)

class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_id: int
    exam_type: str
    type: str
    question_text: str
    choices: list[str]
    source: str | None
    difficulty: int
    created_at: datetime
    quality_score: float
    generated_at: datetime
    model_version: str

class AnswerRequest(BaseModel):
    selected_index: int = Field(ge=0, le=3)
    user_id: int = Field(default=1, ge=1)
    time_spent: int | None = Field(default=None, ge=0)

class AnswerResponse(BaseModel):
    question_id: int
    selected_index: int
    correct_index: int
    is_correct: bool
    explanation: str

class WrongNoteResponse(BaseModel):
    question_id: int
    question_text: str
    choices: list[str]
    selected_index: int
    answered_at: datetime
    topic_id: int
    topic_name: str
    summary_text: str

class AccuracyStat(BaseModel):
    name: str
    total: int
    correct: int
    accuracy: float

class StatsResponse(BaseModel):
    subject_stats: list[AccuracyStat]
    domain_stats: list[AccuracyStat]
    recent_7_days_count: int
    weak_domains: list[AccuracyStat]

class ReviewQueueItem(BaseModel):
    schedule_id: int
    topic_id: int
    topic_name: str
    domain_name: str
    subject_name: str
    next_review_at: datetime
    overdue_days: int
    interval_days: int
    repetition_count: int
class EssayQuestionResponse(BaseModel):
    id: int
    topic_id: int
    exam_type: str
    type: str
    question_text: str
    difficulty: int
    created_at: datetime

class EssaySubmitRequest(BaseModel):
    user_id: int = Field(default=1, ge=1)
    answer_text: str = Field(min_length=1, max_length=10000)

class EssayFeedbackResponse(BaseModel):
    essay_answer_id: int
    question_id: int
    score: float
    covered_keywords: list[dict]
    missing_keywords: list[dict]
    feedback_text: str
    improvement_suggestion: str
    disclaimer: str

class EssayHistoryItem(BaseModel):
    id: int
    question_id: int
    question_text: str
    answer_text: str
    ai_feedback: dict
    score: float
    created_at: datetime


class AdminTopicRequest(BaseModel):
    id: int | None = None
    domain_id: int
    name: str = Field(min_length=1, max_length=200)
    summary_text: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    difficulty_level: int = Field(default=1, ge=1, le=3)
    content_version: str = Field(default="v1", max_length=80)


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    doc_type: str
    subject_id: int
    uploaded_at: datetime
    version: str
    status: str
    error_message: str | None


class DocumentEmbeddingResponse(BaseModel):
    id: int
    topic_id: int
    topic_name: str
    chunk_preview: str


class DocumentDetailResponse(SourceDocumentResponse):
    embeddings: list[DocumentEmbeddingResponse]


class ReassignEmbeddingRequest(BaseModel):
    topic_id: int


class ReferenceQuestionRequest(BaseModel):
    source_document_id: int
    topic_id: int
    original_text: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1900, le=2100)
    note: str | None = None


class ReferenceQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_document_id: int
    topic_id: int
    original_text: str
    year: int | None
    note: str | None
