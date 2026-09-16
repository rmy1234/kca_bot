"""Per-key request allowances, used to cap how fast one account can spend LLM quota."""
import time

_MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    """Allows max_events per key within window_seconds, counted over a rolling window."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        return [stamp for stamp in self._events.get(key, []) if now - stamp < self.window_seconds]

    def _sweep_expired(self, now: float) -> None:
        for key in [key for key, stamps in self._events.items() if not self._recent(key, now)]:
            del self._events[key]

    def consume(self, key: str) -> float:
        """Spend one allowance and return 0.0, or return the seconds to wait when none is left."""
        now = time.monotonic()
        events = self._recent(key, now)
        if len(events) >= self.max_events:
            return self.window_seconds - (now - events[0])
        if len(self._events) >= _MAX_TRACKED_KEYS:
            self._sweep_expired(now)
        self._events[key] = events + [now]
        return 0.0

    def clear(self) -> None:
        self._events.clear()
