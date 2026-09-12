from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

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
    topic_id: int | None = None
    subject_id: int | None = None
    count: int = Field(1, ge=1, le=10)

    @model_validator(mode="after")
    def check_scope(self):
        if (self.topic_id is None) == (self.subject_id is None):
            raise ValueError("topic_id와 subject_id 중 하나만 지정하세요.")
        return self

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
    verification_status: str

class PoolQuestionResponse(QuestionResponse):
    last_is_correct: bool | None = None

class LLMStatusResponse(BaseModel):
    provider: str
    active_model: str
    primary_model: str | None
    fallback_model: str | None
    fallback_active: bool
    fallback_until: datetime | None
    fallback_reason: str | None

class GenerateQuestionsResponse(BaseModel):
    questions: list[QuestionResponse]
    requested: int
    rejected: int
    unverified: int

class AnswerRequest(BaseModel):
    selected_index: int = Field(ge=0, le=3)
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
    subject_id: int | None
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


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str | None
    is_admin: bool
    target_exam_date: date | None

class UpdateProfileRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    email: EmailStr | None = None
    new_password: str | None = Field(None, min_length=8, max_length=200)
    # Required to confirm an email or password change; not needed for a name-only update.
    current_password: str | None = None
