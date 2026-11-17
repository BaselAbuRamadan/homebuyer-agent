"""Usage limits for the public demo. Plain Python (no Streamlit), so it is unit-tested.

The app already limits each visitor to a few questions per browser session, but a
refresh starts a new session. DailyLimit counts questions from ALL visitors together
and stops at a fixed number per day, which caps the worst-case OpenAI bill.
"""
import threading
from collections.abc import Callable
from datetime import date


class DailyLimit:
    """A shared counter that allows at most `limit` questions per calendar day.

    The app keeps ONE instance in server memory (via st.cache_resource), shared by
    every visitor. It resets at midnight (server time) and whenever the app restarts,
    so it is a safety net, not exact accounting: the OpenAI budget limit is the hard stop.
    """

    def __init__(self, limit: int, today: Callable[[], date] = date.today):
        self.limit = limit
        self._today = today                # injectable so tests can change the date
        self._day: date | None = None
        self._count = 0
        self._lock = threading.Lock()      # visitors run in parallel threads

    def try_use(self) -> bool:
        """Count one question if today's limit allows it. Returns False when the limit is reached."""
        with self._lock:
            day = self._today()
            if day != self._day:           # a new day: start counting again
                self._day, self._count = day, 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    def used_today(self) -> int:
        with self._lock:
            return self._count if self._day == self._today() else 0
