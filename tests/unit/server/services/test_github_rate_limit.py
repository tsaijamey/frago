"""Unit tests for GitHubRateLimitManager (Phase 5: 原零覆盖).

以单元测试为准：断言契约——header 解析（大小写不敏感 + 解析失败容错）、backoff 累积
与上限、recommended_delay 的 hard/soft/normal 三档、should_skip_refresh、adaptive_interval。
纯内存状态，直接实例化。
"""

import time

from frago.recipes.github_rate_limit import GitHubRateLimitManager


def _mgr():
    return GitHubRateLimitManager()


def test_update_from_headers_case_insensitive():
    m = _mgr()
    m.update_from_headers({"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4999",
                           "x-ratelimit-reset": "1700000000"})
    s = m.get_status()
    assert s["limit"] == 5000
    assert s["remaining"] == 4999
    assert s["reset_timestamp"] == 1700000000.0


def test_update_from_headers_bad_value_is_tolerated():
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "not-a-number"})
    # parse error swallowed; limit stays default
    assert m.get_status()["limit"] == 60


def test_update_resets_backoff():
    m = _mgr()
    m.record_error(is_rate_limit=True)
    assert m.get_status()["backoff_multiplier"] > 1.0
    m.update_from_headers({"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "60"})
    assert m.get_status()["backoff_multiplier"] == 1.0
    assert m.get_status()["consecutive_errors"] == 0


def test_record_error_backoff_growth_and_caps():
    m = _mgr()
    for _ in range(10):
        m.record_error(is_rate_limit=True)
    assert m.get_status()["backoff_multiplier"] == 64.0  # rate-limit cap

    m2 = _mgr()
    for _ in range(10):
        m2.record_error(is_rate_limit=False)
    assert m2.get_status()["backoff_multiplier"] == 16.0  # other-error cap


def test_recommended_delay_normal():
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "100"})
    assert m.get_recommended_delay() == 0.1  # normal, backoff 1.0


def test_recommended_delay_soft_limit():
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "15"})  # 15% ≤ 20%
    assert m.get_recommended_delay() == 5.0


def test_recommended_delay_hard_limit_waits_until_reset():
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "1"})  # 1% ≤ 5%
    m._state.reset_timestamp = time.time() + 120
    delay = m.get_recommended_delay()
    assert 100 < delay <= 121  # waits ~until reset


def test_should_skip_refresh():
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "2"})
    assert m.should_skip_refresh() is True
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "50"})
    assert m.should_skip_refresh() is False


def test_adaptive_interval():
    base = 60.0
    m = _mgr()
    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "80"})
    assert m.get_adaptive_interval(base) == base  # normal

    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "15"})
    assert m.get_adaptive_interval(base) == base * 2  # soft → double

    m.update_from_headers({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "1"})
    m._state.reset_timestamp = time.time() + 10
    assert m.get_adaptive_interval(base) >= 600  # hard → at least 10 min
