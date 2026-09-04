from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor


@dataclass(frozen=True)
class SM2State:
    ease_factor: float = 2.5
    interval_days: int = 0
    repetition_count: int = 0


def update_sm2(state: SM2State, quality: int, reviewed_at: datetime) -> tuple[SM2State, datetime]:
    """Return the next SM-2 state and review time. quality is an integer from 0 to 5."""
    if quality < 0 or quality > 5:
        raise ValueError("quality must be between 0 and 5")

    ease_factor = max(
        1.3,
        state.ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02),
    )

    if quality < 3:
        repetition_count = 0
        interval_days = 1
    elif state.repetition_count == 0:
        repetition_count = 1
        interval_days = 1
    elif state.repetition_count == 1:
        repetition_count = 2
        interval_days = 6
    else:
        repetition_count = state.repetition_count + 1
        interval_days = max(1, floor(state.interval_days * ease_factor))

    next_state = SM2State(
        ease_factor=round(ease_factor, 4),
        interval_days=interval_days,
        repetition_count=repetition_count,
    )
    return next_state, reviewed_at + timedelta(days=interval_days)

