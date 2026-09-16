import ast
import pathlib

import pytest
from pydantic import ValidationError

from app import auth
from app.schemas import RegisterRequest, UpdateProfileRequest

MAIN_SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py"
# Anything that spends LLM quota or writes shared state must not be reachable without a token.
PUBLIC_ROUTES = {"/health", "/auth/register", "/auth/login", "/subjects", "/subjects/{subject_id}/topics"}
# Dependencies that authenticate the caller; llm_quota_guard authenticates and then meters LLM use.
AUTH_DEPENDENCIES = ("get_current_user", "require_admin", "llm_quota_guard")
# Every endpoint that reaches an LLM has to go through the metered dependency, not plain authentication.
LLM_ROUTES = {
    "/questions/generate",
    "/questions/{question_id}/regenerate-similar",
    "/questions/reverify",
    "/essay-questions/generate",
    "/essay-questions/{question_id}/submit",
}


def _routes():
    tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.args
            ):
                yield decorator.func.attr.upper(), decorator.args[0].value, ast.unparse(node.args)


def test_every_non_public_route_requires_authentication():
    unprotected = [
        f"{method} {path}"
        for method, path, signature in _routes()
        if path not in PUBLIC_ROUTES and not any(dependency in signature for dependency in AUTH_DEPENDENCIES)
    ]
    assert unprotected == []


def test_every_llm_route_is_metered():
    unmetered = [f"{method} {path}" for method, path, signature in _routes() if path in LLM_ROUTES and "llm_quota_guard" not in signature]
    assert unmetered == []


def test_admin_routes_require_admin_privileges():
    not_admin_gated = [f"{method} {path}" for method, path, signature in _routes() if path.startswith("/admin/") and "require_admin" not in signature]
    assert not_admin_gated == []


@pytest.fixture(autouse=True)
def clear_login_state():
    auth._login_failures.clear()
    yield
    auth._login_failures.clear()


def test_login_is_allowed_until_the_attempt_limit_is_reached():
    for _ in range(auth.LOGIN_MAX_ATTEMPTS - 1):
        auth.record_login_failure("user@example.com", "10.0.0.1")
    assert auth.login_retry_after("user@example.com", "10.0.0.1") == 0.0


def test_login_is_throttled_after_repeated_failures():
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        auth.record_login_failure("user@example.com", "10.0.0.1")
    assert auth.login_retry_after("user@example.com", "10.0.0.1") > 0


def test_throttling_is_scoped_to_the_email_and_client():
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        auth.record_login_failure("user@example.com", "10.0.0.1")
    assert auth.login_retry_after("other@example.com", "10.0.0.1") == 0.0
    assert auth.login_retry_after("user@example.com", "10.0.0.2") == 0.0


def test_a_successful_login_clears_the_failure_count():
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        auth.record_login_failure("user@example.com", "10.0.0.1")
    auth.clear_login_failures("user@example.com", "10.0.0.1")
    assert auth.login_retry_after("user@example.com", "10.0.0.1") == 0.0


def test_expired_failures_stop_counting(monkeypatch):
    auth.record_login_failure("user@example.com", "10.0.0.1")
    moved_on = [False]
    real_monotonic = auth.time.monotonic
    monkeypatch.setattr(auth.time, "monotonic", lambda: real_monotonic() + (auth.LOGIN_WINDOW_SECONDS + 1 if moved_on[0] else 0))
    moved_on[0] = True
    for _ in range(auth.LOGIN_MAX_ATTEMPTS - 1):
        auth.record_login_failure("user@example.com", "10.0.0.1")
    assert auth.login_retry_after("user@example.com", "10.0.0.1") == 0.0


@pytest.mark.parametrize("password", ["alllettersonly", "12345678901", "password1", "aaaaaaa1", "Password"])
def test_registration_rejects_weak_passwords(password):
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=password, name="학습자")


@pytest.mark.parametrize("password", ["studyKca2026", "s3cure-pass9", "Gongbu1234!"])
def test_registration_accepts_strong_passwords(password):
    assert RegisterRequest(email="user@example.com", password=password, name="학습자").password == password


def test_password_change_is_held_to_the_same_policy():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(new_password="password1", current_password="whatever")
    assert UpdateProfileRequest(new_password="studyKca2026", current_password="whatever").new_password == "studyKca2026"


def test_a_name_only_update_needs_no_password():
    assert UpdateProfileRequest(name="새 이름").new_password is None


def test_the_essay_grading_prompt_marks_the_user_answer_as_untrusted():
    from app.prompts.essay_grading import ESSAY_GRADING_PROMPT

    assert "untrusted" in ESSAY_GRADING_PROMPT


def test_self_service_registration_is_closed_by_default():
    from app.core.config import Settings

    assert Settings(_env_file=None).registration_open is False


def test_an_unknown_account_still_pays_the_password_hashing_cost():
    from app import auth

    calls = []
    original = auth.verify_password
    auth.verify_password = lambda raw, hashed: calls.append(hashed) or original(raw, hashed)
    try:
        assert auth.verify_password_constant_time("anything", None) is False
    finally:
        auth.verify_password = original
    # A missing account must not short-circuit, or its faster reply reveals that the email is unused.
    assert calls == [auth._ABSENT_ACCOUNT_HASH]


def test_the_llm_limiter_stops_one_account_from_draining_the_quota():
    from app.throttle import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(max_events=3, window_seconds=3600.0)
    assert [limiter.consume("7") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.consume("7") > 0
    # The cap is per account, so one heavy user cannot lock everyone else out.
    assert limiter.consume("8") == 0.0
