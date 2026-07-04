import threading
import time


class RateLimiter:
    """Token bucket: refills continuously, blocks the caller instead of raising when empty."""

    def __init__(self, rate: int, per_seconds: float) -> None:
        self._rate = rate
        self._per_seconds = per_seconds
        self._tokens = float(rate)
        self._updated_at = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated_at
            self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / self._per_seconds))
            self._updated_at = now
            if self._tokens < 1:
                wait = (1 - self._tokens) * (self._per_seconds / self._rate)
                time.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
