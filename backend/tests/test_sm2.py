from datetime import datetime

import pytest

from app.srs.sm2 import SM2State, update_sm2


def test_correct_answers_follow_sm2_intervals():
    reviewed_at = datetime(2026, 1, 1)
    state = SM2State()

    state, next_review = update_sm2(state, 4, reviewed_at)
    assert state.interval_days == 1
    assert state.repetition_count == 1
    assert next_review == datetime(2026, 1, 2)

    state, next_review = update_sm2(state, 4, next_review)
    assert state.interval_days == 6
    assert state.repetition_count == 2
    assert next_review == datetime(2026, 1, 8)

    state, _ = update_sm2(state, 4, next_review)
    assert state.interval_days > 6
    assert state.repetition_count == 3


def test_wrong_answer_resets_repetition():
    state, next_review = update_sm2(SM2State(ease_factor=2.6, interval_days=10, repetition_count=3), 2, datetime(2026, 1, 10))
    assert state.repetition_count == 0
    assert state.interval_days == 1
    assert next_review == datetime(2026, 1, 11)


def test_quality_must_be_valid():
    with pytest.raises(ValueError):
        update_sm2(SM2State(), 6, datetime(2026, 1, 1))

