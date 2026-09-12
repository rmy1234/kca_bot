import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from google.genai import errors, types
import httpx
from pydantic import BaseModel
import pytest

from app import llm
from app.db.models import Topic
from app.llm import GeneratedQuestion, LLMUnavailableError, QuestionRequest, _QuestionItem, collect_generated, retry_delay_seconds, verify_questions
from app.prompts.question_generation import build_question_prompt, build_verification_prompt

GEMINI_SETTINGS = SimpleNamespace(llm_provider="gemini", gemini_api_key="test-key", llm_model="test-model")
MOCK_SETTINGS = SimpleNamespace(llm_provider="gemini", gemini_api_key=None)
OLLAMA_SETTINGS = SimpleNamespace(llm_provider="ollama", gemini_api_key=None, ollama_base_url="http://ollama.test", ollama_model="qwen3.5:9b", ollama_num_ctx=4096, ollama_think=False, ollama_timeout_seconds=30.0, ollama_fallback_model=None, ollama_fallback_minutes=60)


@pytest.fixture(autouse=True)
def reset_ollama_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_fallback_until", None)
    monkeypatch.setattr(llm, "_fallback_reason", None)


def _topic(topic_id, name="토픽"):
    return Topic(id=topic_id, domain_id=1, name=name, summary_text=f"{name} 세세항목", keywords=[name], difficulty_level=1)


def _question(topic_id, text="문제", choices=None, answer_index=0):
    return GeneratedQuestion(topic_id=topic_id, question=text, choices=choices or ["a", "b", "c", "d"], answer_index=answer_index, explanation="해설", difficulty=1)


def _item(topic_id, text):
    return _QuestionItem(topic_id=topic_id, question=text, choices=["a", "b", "c", "d"], answer_index=0, explanation="해설", difficulty=1)


def _api_error(code, retry_delay=None, message="error"):
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}] if retry_delay else []
    return errors.APIError(code, {"error": {"code": code, "message": message, "status": "ERROR", "details": details}})


class _Payload(BaseModel):
    ok: bool


def _call_structured():
    return asyncio.run(llm.generate_structured(_Payload, "prompt", max_output_tokens=100))


# ---------------------------------------------------------------------------
# backend selection, prompts, and batch collection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("settings", "expected"), [(GEMINI_SETTINGS, "gemini"), (MOCK_SETTINGS, "mock"), (OLLAMA_SETTINGS, "ollama")])
def test_llm_backend_follows_provider_and_key(monkeypatch, settings, expected):
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    assert llm.llm_backend() == expected


def test_model_label_records_local_model(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: OLLAMA_SETTINGS)
    assert llm.model_label() == "ollama:qwen3.5:9b"


def test_question_prompt_lists_each_topic_with_its_count():
    prompt = build_question_prompt([QuestionRequest(_topic(3, "스푸핑 공격"), 2), QuestionRequest(_topic(7, "스캐닝"), 1)])
    assert "topic_id=3: 스푸핑 공격\nQuestions to write: 2" in prompt
    assert "topic_id=7: 스캐닝\nQuestions to write: 1" in prompt
    assert "exactly 3 questions" in prompt


def test_verification_prompt_includes_marked_answer_and_criteria():
    prompt = build_verification_prompt([(0, _topic(3, "스푸핑 공격"), _question(3, answer_index=2))])
    assert "Marked answer_index: 2" in prompt
    assert "Exam criteria: 스푸핑 공격 세세항목" in prompt
    assert "Explanation: 해설" in prompt


def test_collect_generated_drops_unknown_topics_and_caps_counts():
    requests = [QuestionRequest(_topic(1), 2), QuestionRequest(_topic(2), 1)]
    items = [_item(1, "a"), _item(9, "unknown"), _item(1, "b"), _item(1, "c"), _item(2, "d"), _item(2, "e")]
    assert [(question.topic_id, question.question) for question in collect_generated(items, requests)] == [(1, "a"), (1, "b"), (2, "d")]


# ---------------------------------------------------------------------------
# Gemini: retry on rate limit / overload
# ---------------------------------------------------------------------------

def test_retry_delay_reads_retry_info():
    assert retry_delay_seconds(_api_error(429, retry_delay="31s")) == 31.0


def test_retry_delay_falls_back_to_message():
    assert retry_delay_seconds(_api_error(429, message="Please retry in 30.5s.")) == 30.5


def test_retry_delay_is_none_without_hint():
    assert retry_delay_seconds(_api_error(503, message="overloaded")) is None


class _FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(text):
    return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)], text=text)


@pytest.fixture
def fake_gemini(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: GEMINI_SETTINGS)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)

    def install(outcomes):
        models = _FakeModels(outcomes)
        monkeypatch.setattr(llm, "get_gemini_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=models)))
        return models

    return install, sleeps


def test_generate_structured_retries_once_after_rate_limit(fake_gemini):
    install, sleeps = fake_gemini
    models = install([_api_error(429, retry_delay="12s"), _response('{"ok": true}')])
    assert _call_structured().ok
    assert models.calls == 2
    assert sleeps == [12.0]


def test_generate_structured_retries_overload_with_default_wait(fake_gemini):
    install, sleeps = fake_gemini
    install([_api_error(503), _response('{"ok": true}')])
    assert _call_structured().ok
    assert sleeps == [llm.DEFAULT_RETRY_WAIT_SECONDS]


def test_generate_structured_gives_up_after_second_rate_limit(fake_gemini):
    install, sleeps = fake_gemini
    install([_api_error(429, retry_delay="12s"), _api_error(429, retry_delay="12s")])
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.code == 429
    assert sleeps == [12.0]


def test_generate_structured_does_not_wait_beyond_cap(fake_gemini):
    install, sleeps = fake_gemini
    models = install([_api_error(429, retry_delay="50s")])
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.retry_after == 50.0
    assert models.calls == 1
    assert sleeps == []


def test_generate_structured_does_not_retry_other_errors(fake_gemini):
    install, sleeps = fake_gemini
    models = install([_api_error(400, message="bad request")])
    with pytest.raises(RuntimeError) as caught:
        _call_structured()
    assert not isinstance(caught.value, LLMUnavailableError)
    assert models.calls == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# Ollama: local model over HTTP
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_ollama(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: OLLAMA_SETTINGS)
    sent = []

    def install(handler):
        def record(request):
            sent.append(request)
            return handler(request)

        monkeypatch.setattr(llm, "_ollama_client", lambda settings: httpx.AsyncClient(base_url=settings.ollama_base_url, transport=httpx.MockTransport(record)))
        return sent

    return install


def test_ollama_sends_schema_and_parses_content(fake_ollama):
    sent = fake_ollama(lambda request: httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "done_reason": "stop"}))
    assert _call_structured().ok
    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/api/chat"
    assert body["model"] == "qwen3.5:9b"
    assert body["format"] == _Payload.model_json_schema()
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {"num_predict": 100, "num_ctx": 4096}


def test_ollama_missing_model_explains_how_to_pull(fake_ollama):
    fake_ollama(lambda request: httpx.Response(404, json={"error": 'model "qwen3.5:9b" not found, try pulling it first'}))
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert "ollama pull qwen3.5:9b" in caught.value.user_message


def test_ollama_unreachable_server_is_reported(fake_ollama):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    fake_ollama(refuse)
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.code == 503
    assert "Ollama가 실행 중인지" in caught.value.user_message


def test_ollama_truncated_output_is_an_error(fake_ollama):
    fake_ollama(lambda request: httpx.Response(200, json={"message": {"content": '{"ok": tr'}, "done_reason": "length"}))
    with pytest.raises(RuntimeError) as caught:
        _call_structured()
    assert not isinstance(caught.value, LLMUnavailableError)
    assert "num_predict" in str(caught.value)


OLLAMA_CLOUD_SETTINGS = SimpleNamespace(**{**vars(OLLAMA_SETTINGS), "ollama_model": "deepseek-v4-flash:cloud"})


@pytest.mark.parametrize("model", ["deepseek-v4-flash:cloud", "gpt-oss:120b-cloud", "deepseek-v4-flash:0731-cloud"])
def test_cloud_model_names_are_detected(model):
    assert llm.is_ollama_cloud_model(model)


def test_local_model_names_are_not_cloud():
    assert not llm.is_ollama_cloud_model("qwen3.5:9b")


def test_ollama_cloud_model_puts_schema_in_prompt_and_parses_fenced_json(monkeypatch, fake_ollama):
    sent = fake_ollama(lambda request: httpx.Response(200, json={"message": {"content": '결과입니다.\n```json\n{"ok": true}\n```'}, "done_reason": "stop"}))
    monkeypatch.setattr(llm, "get_settings", lambda: OLLAMA_CLOUD_SETTINGS)
    assert _call_structured().ok
    body = json.loads(sent[0].content)
    assert body["model"] == "deepseek-v4-flash:cloud"
    assert "format" not in body
    assert "JSON schema" in body["messages"][0]["content"]
    assert '"ok"' in body["messages"][0]["content"]


def test_ollama_cloud_without_signin_explains_signin(fake_ollama):
    fake_ollama(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.code == 503
    assert "ollama signin" in caught.value.user_message


def test_ollama_usage_limit_is_reported_as_rate_limit(fake_ollama):
    fake_ollama(lambda request: httpx.Response(429, json={"error": "usage limit reached"}))
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.code == 429
    assert "사용량 한도" in caught.value.user_message


def test_extract_json_object_handles_fences_and_prose():
    assert llm.extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert llm.extract_json_object('설명 {"a": {"b": 2}} 끝') == '{"a": {"b": 2}}'
    assert llm.extract_json_object('{"a": 1}') == '{"a": 1}'


FALLBACK_SETTINGS = SimpleNamespace(**{**vars(OLLAMA_CLOUD_SETTINGS), "ollama_fallback_model": "qwen3.5:9b"})


def _limit_cloud_model(request):
    if json.loads(request.content)["model"] == "deepseek-v4-flash:cloud":
        return httpx.Response(429, json={"error": "usage limit reached"})
    return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "done_reason": "stop"})


def _sent_models(sent):
    return [json.loads(request.content)["model"] for request in sent]


def test_usage_limit_switches_to_fallback_model(monkeypatch, fake_ollama):
    sent = fake_ollama(_limit_cloud_model)
    monkeypatch.setattr(llm, "get_settings", lambda: FALLBACK_SETTINGS)
    assert _call_structured().ok
    assert _sent_models(sent) == ["deepseek-v4-flash:cloud", "qwen3.5:9b"]
    assert "format" in json.loads(sent[1].content)
    status = llm.llm_status()
    assert status["fallback_active"] is True
    assert status["active_model"] == "ollama:qwen3.5:9b"
    assert status["fallback_until"] is not None
    assert "사용량 한도" in status["fallback_reason"]


def test_subscription_required_also_switches_to_fallback_model(monkeypatch, fake_ollama):
    def require_subscription(request):
        if json.loads(request.content)["model"] == "deepseek-v4-flash:cloud":
            return httpx.Response(402, json={"error": "this model requires a subscription or usage credits"})
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "done_reason": "stop"})

    sent = fake_ollama(require_subscription)
    monkeypatch.setattr(llm, "get_settings", lambda: FALLBACK_SETTINGS)
    assert _call_structured().ok
    assert _sent_models(sent) == ["deepseek-v4-flash:cloud", "qwen3.5:9b"]
    assert "크레딧" in llm.llm_status()["fallback_reason"]


def test_subscription_required_without_fallback_is_explained(fake_ollama, monkeypatch):
    fake_ollama(lambda request: httpx.Response(402, json={"error": "this model requires a subscription or usage credits"}))
    monkeypatch.setattr(llm, "get_settings", lambda: OLLAMA_CLOUD_SETTINGS)
    with pytest.raises(LLMUnavailableError) as caught:
        _call_structured()
    assert caught.value.code == 402
    assert "구독 또는 사용 크레딧" in caught.value.user_message


def test_fallback_skips_cloud_model_until_cooldown_ends(monkeypatch, fake_ollama):
    sent = fake_ollama(_limit_cloud_model)
    monkeypatch.setattr(llm, "get_settings", lambda: FALLBACK_SETTINGS)
    _call_structured()
    _call_structured()
    assert _sent_models(sent) == ["deepseek-v4-flash:cloud", "qwen3.5:9b", "qwen3.5:9b"]
    monkeypatch.setattr(llm, "_fallback_until", datetime.now(timezone.utc) - timedelta(seconds=1))
    assert llm.llm_status()["fallback_active"] is False
    _call_structured()
    assert _sent_models(sent)[3] == "deepseek-v4-flash:cloud"


def test_other_cloud_errors_do_not_switch_models(monkeypatch, fake_ollama):
    sent = fake_ollama(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    monkeypatch.setattr(llm, "get_settings", lambda: FALLBACK_SETTINGS)
    with pytest.raises(LLMUnavailableError):
        _call_structured()
    assert _sent_models(sent) == ["deepseek-v4-flash:cloud"]
    assert llm.llm_status()["fallback_active"] is False


# ---------------------------------------------------------------------------
# batch verification
# ---------------------------------------------------------------------------

@pytest.fixture
def gemini_enabled(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: GEMINI_SETTINGS)


def test_verify_questions_maps_batch_results(monkeypatch, gemini_enabled):
    captured = {}

    async def fake_structured(schema, prompt, **kwargs):
        captured["prompt"] = prompt
        return schema(results=[{"index": 0, "is_valid": True}, {"index": 2, "is_valid": False, "reason": "정답이 없음"}])

    monkeypatch.setattr(llm, "generate_structured", fake_structured)
    topic = _topic(1)
    items = [(topic, _question(1)), (topic, _question(1, choices=["a", "a", "b", "c"])), (topic, _question(1)), (topic, _question(1))]
    verdicts = asyncio.run(verify_questions(items))
    assert verdicts == [("valid", None), ("invalid", "choices must be unique"), ("invalid", "정답이 없음"), ("unverified", "verification_result_missing")]
    assert "index=1" not in captured["prompt"]


def test_verify_questions_keeps_questions_unverified_when_call_fails(monkeypatch, gemini_enabled):
    async def failing_structured(schema, prompt, **kwargs):
        raise LLMUnavailableError("rate limited", code=429, retry_after=40.0)

    monkeypatch.setattr(llm, "generate_structured", failing_structured)
    topic = _topic(1)
    verdicts = asyncio.run(verify_questions([(topic, _question(1)), (topic, _question(1))]))
    assert [status for status, _ in verdicts] == ["unverified", "unverified"]
    assert all("verification_call_failed" in reason for _, reason in verdicts)


def test_verify_questions_mock_mode_checks_topic_name(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: MOCK_SETTINGS)
    topic = _topic(1, "스캐닝")
    verdicts = asyncio.run(verify_questions([(topic, _question(1, text="스캐닝 관련 문제")), (topic, _question(1, text="무관한 문제"))]))
    assert [status for status, _ in verdicts] == ["valid", "invalid"]
