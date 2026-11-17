"""Tests for the shared daily question limit. No API calls, no Streamlit."""
import threading
from datetime import date

from homebuyer_agent.usage import DailyLimit


def test_allows_up_to_the_limit_then_stops():
    limit = DailyLimit(3)
    assert [limit.try_use() for _ in range(5)] == [True, True, True, False, False]
    assert limit.used_today() == 3


def test_resets_on_a_new_day():
    today = [date(2026, 11, 17)]
    limit = DailyLimit(1, today=lambda: today[0])
    assert limit.try_use() and not limit.try_use()
    today[0] = date(2026, 11, 18)
    assert limit.try_use()


def test_zero_means_closed():
    assert DailyLimit(0).try_use() is False


def test_parallel_visitors_never_exceed_the_limit():
    limit = DailyLimit(50)
    allowed = []

    def visitor():
        for _ in range(20):
            if limit.try_use():
                allowed.append(1)

    threads = [threading.Thread(target=visitor) for _ in range(10)]   # 200 attempts at once
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 50
