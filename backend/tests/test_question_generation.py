import pytest
from pydantic import ValidationError

from app.db.models import Question, Topic
from app.main import allocate_question_counts, select_pool_questions
from app.schemas import GenerateQuestionsRequest


def _topics(count):
    return [Topic(id=index, domain_id=1, name=f"토픽 {index}", summary_text="", keywords=[]) for index in range(1, count + 1)]


def _questions(count):
    return [Question(id=index, topic_id=1, question_text=f"문제 {index}", choices=["a", "b", "c", "d"], answer_index=0) for index in range(1, count + 1)]


@pytest.mark.parametrize("count", [1, 5, 10])
def test_allocation_matches_requested_count(count):
    plan = allocate_question_counts(_topics(8), count)
    assert sum(topic_count for _, topic_count in plan) == count


def test_allocation_uses_distinct_topics_when_count_fits():
    plan = allocate_question_counts(_topics(8), 5)
    assert len(plan) == 5
    assert len({topic.id for topic, _ in plan}) == 5
    assert all(topic_count == 1 for _, topic_count in plan)


def test_allocation_spreads_evenly_when_count_exceeds_topics():
    plan = allocate_question_counts(_topics(6), 10)
    counts = sorted(topic_count for _, topic_count in plan)
    assert len(plan) == 6
    assert counts[-1] - counts[0] <= 1


def test_generate_request_accepts_topic_or_subject():
    assert GenerateQuestionsRequest(topic_id=1, count=5).subject_id is None
    assert GenerateQuestionsRequest(subject_id=1, count=10).topic_id is None


@pytest.mark.parametrize("payload", [{"count": 1}, {"topic_id": 1, "subject_id": 1, "count": 1}])
def test_generate_request_requires_exactly_one_scope(payload):
    with pytest.raises(ValidationError):
        GenerateQuestionsRequest(**payload)


def test_pool_unanswered_excludes_answered_questions():
    picked = select_pool_questions(_questions(5), {1: True, 2: False}, "unanswered", 10)
    assert sorted(question.id for question in picked) == [3, 4, 5]


def test_pool_wrong_selects_questions_whose_last_attempt_was_wrong():
    picked = select_pool_questions(_questions(5), {1: True, 2: False, 3: False}, "wrong", 10)
    assert sorted(question.id for question in picked) == [2, 3]


def test_pool_all_puts_unanswered_first_and_respects_limit():
    picked = select_pool_questions(_questions(6), {1: True, 2: False, 3: True}, "all", 4)
    assert len(picked) == 4
    assert {question.id for question in picked[:3]} == {4, 5, 6}


def test_pool_without_limit_returns_every_match():
    picked = select_pool_questions(_questions(30), {1: True}, "all", None)
    assert len(picked) == 30
    assert {question.id for question in picked} == set(range(1, 31))
