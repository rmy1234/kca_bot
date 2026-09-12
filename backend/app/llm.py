import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Protocol, TypeVar

from google import genai
from google.genai import errors, types
import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings, get_settings
from app.db.models import Topic
from app.prompts.question_generation import build_question_prompt, build_verification_prompt

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

@dataclass
class GeneratedQuestion:
    topic_id: int
    question: str
    choices: list[str]
    answer_index: int
    explanation: str
    difficulty: int

@dataclass
class QuestionRequest:
    topic: Topic
    count: int
    context: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

class QuestionGenerator(Protocol):
    async def generate(self, requests: list[QuestionRequest]) -> list[GeneratedQuestion]: ...

class MockQuestionGenerator:
    async def generate(self, requests: list[QuestionRequest]) -> list[GeneratedQuestion]:
        prompt_context = build_question_prompt(requests)
        questions = []
        for request in requests:
            topic = request.topic
            keyword = topic.keywords[0] if topic.keywords else topic.name
            questions.extend(GeneratedQuestion(topic_id=topic.id, question=f"[Mock {i + 1}] Which choice best matches the topic '{topic.name}'?", choices=[keyword, "Unrelated concept", "Out-of-scope concept", "None of the above"], answer_index=0, explanation=f"Generated with {len(prompt_context)} characters of Topic and RAG context.", difficulty=topic.difficulty_level) for i in range(request.count))
        return questions


def llm_backend() -> str:
    """Return "ollama", "gemini", or "mock" (Gemini selected without an API key)."""
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return "ollama"
    return "gemini" if settings.gemini_api_key else "mock"


def model_label() -> str:
    backend = llm_backend()
    if backend == "ollama":
        return f"ollama:{active_ollama_model()}"
    if backend == "gemini":
        return f"gemini:{get_settings().llm_model}"
    return "mock-v1"


class LLMUnavailableError(RuntimeError):
    """The LLM could not serve the request: a persistent rate limit/overload, or an unreachable local model."""

    def __init__(self, message: str, code: int, retry_after: float, user_message: str | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.user_message = user_message


# While set and in the future, the primary Ollama model hit its usage limit and the fallback model serves requests.
_fallback_until: datetime | None = None
_fallback_reason: str | None = None
# Ollama returns 429 when a cloud model's usage limit is reached and 402 when the account needs a subscription or credits for it.
FALLBACK_REASONS = {402: "클라우드 모델에 Ollama 구독 또는 사용 크레딧이 필요합니다.", 429: "클라우드 모델의 사용량 한도에 도달했습니다."}


def active_ollama_model() -> str:
    settings = get_settings()
    if settings.ollama_fallback_model and _fallback_until and datetime.now(timezone.utc) < _fallback_until:
        return settings.ollama_fallback_model
    return settings.ollama_model


def llm_status() -> dict:
    backend = llm_backend()
    settings = get_settings()
    fallback_active = backend == "ollama" and active_ollama_model() != settings.ollama_model
    return {
        "provider": backend,
        "active_model": model_label(),
        "primary_model": settings.ollama_model if backend == "ollama" else None,
        "fallback_model": (settings.ollama_fallback_model or None) if backend == "ollama" else None,
        "fallback_active": fallback_active,
        "fallback_until": _fallback_until if fallback_active else None,
        "fallback_reason": _fallback_reason if fallback_active else None,
    }


_client: genai.Client | None = None
# Generation, verification, and essay calls can overlap; cap concurrent LLM requests.
_llm_slots = asyncio.Semaphore(4)

RETRYABLE_STATUS_CODES = {429, 503}
# Free-tier 429 responses ask to wait about 30-50 seconds; wait only for the shorter ones to keep requests responsive.
MAX_RETRY_WAIT_SECONDS = 35.0
DEFAULT_RETRY_WAIT_SECONDS = 5.0


def retry_delay_seconds(exc: errors.APIError) -> float | None:
    details = exc.details if isinstance(exc.details, dict) else {}
    for item in details.get("error", {}).get("details") or []:
        delay = item.get("retryDelay") if isinstance(item, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    match = re.search(r"retry in ([\d.]+)s", str(exc.message or ""))
    return float(match.group(1)) if match else None


def get_gemini_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=get_settings().gemini_api_key)
    return _client


async def _gemini_generate(schema: type[BaseModel], prompt: str, max_output_tokens: int, thinking_level: types.ThinkingLevel) -> str:
    settings = get_settings()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema.model_json_schema(),
        # max_output_tokens also covers thinking tokens, so a low budget here
        # truncates the JSON payload mid-string instead of erroring.
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
    )
    for attempt in range(2):
        try:
            async with _llm_slots:
                response = await get_gemini_client().aio.models.generate_content(model=settings.llm_model, contents=prompt, config=config)
            break
        except errors.APIError as exc:
            if exc.code not in RETRYABLE_STATUS_CODES:
                raise RuntimeError(f"Gemini request failed: {exc}") from exc
            delay = retry_delay_seconds(exc) or DEFAULT_RETRY_WAIT_SECONDS
            if attempt == 1 or delay > MAX_RETRY_WAIT_SECONDS:
                raise LLMUnavailableError(f"Gemini request failed: {exc}", code=exc.code, retry_after=delay) from exc
            # Wait outside the concurrency slot so other calls are not blocked meanwhile.
            await asyncio.sleep(delay)
    finish_reason = response.candidates[0].finish_reason if response.candidates else None
    if finish_reason == types.FinishReason.MAX_TOKENS:
        raise RuntimeError(f"Gemini response hit max_output_tokens ({max_output_tokens}) before completing the JSON payload")
    return response.text


def is_ollama_cloud_model(model: str) -> bool:
    """Cloud models are tagged like "deepseek-v4-flash:cloud" or "gpt-oss:120b-cloud"."""
    return model.endswith("cloud")


def extract_json_object(text: str) -> str:
    """Strip markdown fences or surrounding prose from a reply whose JSON format was not enforced."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start:end + 1] if start != -1 and end > start else stripped


def _ollama_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds)


async def _ollama_generate(schema: type[BaseModel], prompt: str, max_output_tokens: int) -> str:
    global _fallback_until, _fallback_reason
    settings = get_settings()
    model = active_ollama_model()
    fallback = settings.ollama_fallback_model
    try:
        return await _ollama_request(model, schema, prompt, max_output_tokens)
    except LLMUnavailableError as exc:
        if exc.code not in FALLBACK_REASONS or not fallback or model == fallback:
            raise
        reason = FALLBACK_REASONS[exc.code]
    # Skip the unavailable primary model for a while instead of failing on it every call.
    _fallback_until = datetime.now(timezone.utc) + timedelta(minutes=settings.ollama_fallback_minutes)
    _fallback_reason = reason
    return await _ollama_request(fallback, schema, prompt, max_output_tokens)


async def _ollama_request(model: str, schema: type[BaseModel], prompt: str, max_output_tokens: int) -> str:
    settings = get_settings()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": settings.ollama_think,
        "options": {"num_predict": max_output_tokens, "num_ctx": settings.ollama_num_ctx},
    }
    if is_ollama_cloud_model(model):
        # Ollama Cloud does not support structured outputs, so the schema goes into the prompt and the reply is parsed leniently.
        payload["messages"][0]["content"] = prompt + "\n\nRespond with only a JSON object, without markdown or commentary, that validates against this JSON schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    else:
        # Local Ollama constrains decoding to this JSON schema, matching Gemini's response_json_schema.
        payload["format"] = schema.model_json_schema()
    try:
        async with _llm_slots:
            async with _ollama_client(settings) as client:
                response = await client.post("/api/chat", json=payload)
    except httpx.TimeoutException as exc:
        raise LLMUnavailableError(f"Ollama request timed out: {exc!r}", code=503, retry_after=0, user_message=f"로컬 LLM이 {settings.ollama_timeout_seconds:.0f}초 안에 응답하지 않았습니다. 문항 수를 줄이거나 OLLAMA_TIMEOUT_SECONDS를 늘리세요.") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailableError(f"Ollama request failed: {exc!r}", code=503, retry_after=0, user_message=f"로컬 LLM(Ollama, {settings.ollama_base_url})에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요.") from exc
    # Returned as 503, not 401, so the frontend does not mistake it for an expired login.
    if response.status_code in (401, 403):
        raise LLMUnavailableError(f"Ollama cloud authorization failed: {response.text[:500]}", code=503, retry_after=0, user_message="Ollama 클라우드 모델을 쓰려면 터미널에서 'ollama signin'으로 Ollama 계정에 로그인하세요.")
    if response.status_code == 402:
        raise LLMUnavailableError(f"Ollama cloud model requires a subscription or credits: {response.text[:500]}", code=402, retry_after=0, user_message=f"'{model}'은(는) 현재 Ollama 계정으로 쓸 수 없는 모델입니다(구독 또는 사용 크레딧 필요). 다른 모델로 바꾸거나 OLLAMA_FALLBACK_MODEL을 설정하세요.")
    if response.status_code == 429:
        raise LLMUnavailableError(f"Ollama usage limit reached: {response.text[:500]}", code=429, retry_after=0, user_message="Ollama 클라우드 사용량 한도에 도달했습니다. 한도가 초기화된 뒤 다시 시도하거나 로컬 모델로 전환하세요.")
    if response.status_code == 404:
        raise LLMUnavailableError(f"Ollama model not found: {response.text[:500]}", code=503, retry_after=0, user_message=f"Ollama에 '{model}' 모델이 없습니다. 'ollama pull {model}'로 먼저 받으세요.")
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama request failed: {response.status_code} {response.text[:500]}")
    body = response.json()
    if body.get("done_reason") == "length":
        raise RuntimeError(f"Ollama response hit num_predict ({max_output_tokens}) or num_ctx ({settings.ollama_num_ctx}) before completing the JSON payload")
    return body.get("message", {}).get("content", "")


async def generate_structured(
    schema: type[_SchemaT],
    prompt: str,
    *,
    max_output_tokens: int,
    thinking_level: types.ThinkingLevel = types.ThinkingLevel.LOW,
) -> _SchemaT:
    if llm_backend() == "ollama":
        text = await _ollama_generate(schema, prompt, max_output_tokens)
    else:
        text = await _gemini_generate(schema, prompt, max_output_tokens, thinking_level)
    try:
        return schema.model_validate_json(extract_json_object(text))
    except (ValidationError, ValueError) as exc:
        raise RuntimeError(f"LLM returned an invalid response: {exc}") from exc


class _QuestionItem(BaseModel):
    topic_id: int
    question: str
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str
    difficulty: int = Field(ge=1, le=3)


class _QuestionBatch(BaseModel):
    questions: list[_QuestionItem]


def collect_generated(items: list[_QuestionItem], requests: list[QuestionRequest]) -> list[GeneratedQuestion]:
    """Keep questions for requested topics only, up to each topic's requested count."""
    remaining = {request.topic.id: request.count for request in requests}
    questions = []
    for item in items:
        if remaining.get(item.topic_id, 0) <= 0:
            continue
        remaining[item.topic_id] -= 1
        questions.append(GeneratedQuestion(topic_id=item.topic_id, question=item.question, choices=item.choices, answer_index=item.answer_index, explanation=item.explanation, difficulty=item.difficulty))
    return questions


class StructuredQuestionGenerator:
    """Generates questions for every requested Topic in a single call to the configured LLM."""

    async def generate(self, requests: list[QuestionRequest]) -> list[GeneratedQuestion]:
        # Up to 10 questions with explanations plus thinking must fit in one response.
        batch = await generate_structured(_QuestionBatch, build_question_prompt(requests), max_output_tokens=32768, thinking_level=types.ThinkingLevel.MEDIUM)
        return collect_generated(batch.questions, requests)


def get_question_generator() -> QuestionGenerator:
    return MockQuestionGenerator() if llm_backend() == "mock" else StructuredQuestionGenerator()


class _VerificationItem(BaseModel):
    index: int
    is_valid: bool
    reason: str | None = None


class _VerificationBatch(BaseModel):
    results: list[_VerificationItem]


Verdict = tuple[str, str | None]


def structural_problem(question: GeneratedQuestion) -> str | None:
    if len(question.choices) != 4:
        return "choices must contain exactly four items"
    if not 0 <= question.answer_index < 4:
        return "answer_index must be between 0 and 3"
    if len(set(question.choices)) != 4:
        return "choices must be unique"
    return None


async def verify_questions(items: list[tuple[Topic, GeneratedQuestion]]) -> list[Verdict]:
    """Return ("valid" | "invalid" | "unverified", reason) per item, using at most one LLM call.

    "unverified" means the verification call itself failed (for example a rate limit), not that the question is wrong.
    """
    verdicts: list[Verdict | None] = []
    pending = []
    use_llm = llm_backend() != "mock"
    for index, (topic, question) in enumerate(items):
        problem = structural_problem(question)
        if problem:
            verdicts.append(("invalid", problem))
        elif not use_llm:
            verdicts.append(("valid", None) if topic.name.lower() in question.question.lower() else ("invalid", "question is outside the selected topic"))
        else:
            verdicts.append(None)
            pending.append((index, topic, question))
    if pending:
        try:
            batch = await generate_structured(_VerificationBatch, build_verification_prompt(pending), max_output_tokens=8192)
        except RuntimeError as exc:
            results, missing_reason = {}, f"verification_call_failed: {exc}"
        else:
            results, missing_reason = {item.index: item for item in batch.results}, "verification_result_missing"
        for index, _, _ in pending:
            result = results.get(index)
            if result is None:
                verdicts[index] = ("unverified", missing_reason)
            else:
                verdicts[index] = ("valid", None) if result.is_valid else ("invalid", result.reason or "rejected without reason")
    return verdicts
