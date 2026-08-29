"""scraper/extraction/rate_limiter.py — per-key Gemini quota."""

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class GoogleRateLimiter:
    """Google AI Studio free-tier budget for one API key."""

    RPM_LIMIT = 5
    RPD_LIMIT = 20
    WINDOW_SECONDS = 60

    def __init__(self):
        self._lock = threading.Lock()
        self._request_timestamps = deque()
        self._daily_count = 0
        self._day_start = time.strftime("%Y-%m-%d")

    def _reset_daily_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._day_start:
            self._daily_count = 0
            self._day_start = today

    @property
    def daily_count(self) -> int:
        with self._lock:
            self._reset_daily_if_needed()
            return self._daily_count

    def daily_quota_exhausted(self) -> bool:
        with self._lock:
            self._reset_daily_if_needed()
            return self._daily_count >= self.RPD_LIMIT

    def acquire(self):
        """Reserve a request slot, blocking for the RPM window if needed."""
        while True:
            with self._lock:
                self._reset_daily_if_needed()
                if self._daily_count >= self.RPD_LIMIT:
                    raise RuntimeError(f"Daily quota exhausted: {self._daily_count}/{self.RPD_LIMIT} requests used today")
                if self._daily_count >= int(self.RPD_LIMIT * 0.8):
                    logger.warning("Rate limiter: daily quota at %d/%d — approaching limit", self._daily_count, self.RPD_LIMIT)
                now = time.time()
                cutoff = now - self.WINDOW_SECONDS
                while self._request_timestamps and self._request_timestamps[0] < cutoff:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < self.RPM_LIMIT:
                    self._request_timestamps.append(now)
                    self._daily_count += 1
                    return
                wait_seconds = (self._request_timestamps[0] + self.WINDOW_SECONDS) - now + 0.5
            logger.info("Rate limiter: at %d RPM, waiting %.1fs for a slot (daily %d/%d)", self.RPM_LIMIT, wait_seconds, self._daily_count, self.RPD_LIMIT)
            time.sleep(max(wait_seconds, 0.5))

    def release_last(self):
        """Hand back the slot just taken — for failures that were not the model's fault."""
        with self._lock:
            if self._request_timestamps:
                self._request_timestamps.pop()
            if self._daily_count > 0:
                self._daily_count -= 1
