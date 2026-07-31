"""Feature 032 (W3) — per-key sliding-window rate limiter unit tests (AC-15, AC-17)."""

import time


def test_allows_up_to_max_then_denies(monkeypatch):
    import app.config as _c
    from app.api.rate_limit import RateLimiter

    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 3)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 100)
    rl = RateLimiter()

    assert all(rl.check("ip1") for _ in range(3))  # first MAX allowed
    assert rl.check("ip1") is False                # over the limit
    assert rl.check("ip2") is True                 # a different key is independent (AC-15)


def test_window_slides(monkeypatch):
    import app.config as _c
    from app.api.rate_limit import RateLimiter

    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 1)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 1)
    rl = RateLimiter()

    assert rl.check("ip") is True
    assert rl.check("ip") is False   # second within the 1s window denied
    time.sleep(1.1)
    assert rl.check("ip") is True     # window slid → allowed again


def test_thresholds_read_from_config_live(monkeypatch):
    # AC-17: changing the config constant changes behavior without touching the limiter.
    import app.config as _c
    from app.api.rate_limit import RateLimiter

    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 100)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 1)
    rl = RateLimiter()
    assert rl.check("k") is True
    assert rl.check("k") is False
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 5)
    rl2 = RateLimiter()
    assert all(rl2.check("k") for _ in range(5))
