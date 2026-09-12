from app.db.models import UserAnswerLog
from app.main import first_attempts


def _log(log_id, question_id, is_correct):
    return UserAnswerLog(id=log_id, user_id=1, question_id=question_id, selected_index=0, is_correct=is_correct)


def test_first_attempts_ignores_later_retries():
    logs = [_log(1, 10, False), _log(2, 11, True), _log(3, 10, True), _log(4, 11, False), _log(5, 10, True)]
    firsts = first_attempts(logs)
    assert [(log.question_id, log.is_correct) for log in firsts] == [(10, False), (11, True)]


def test_first_attempts_keeps_every_question_answered_once():
    logs = [_log(1, 10, True), _log(2, 11, False), _log(3, 12, True)]
    assert first_attempts(logs) == logs
