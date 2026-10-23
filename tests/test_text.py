import datetime as dt

from teo.text import RateLimiter, anon, chunk


def test_short_text_is_one_part():
    assert chunk('hello') == ['hello']


def test_parts_respect_the_limit():
    text = '\n'.join('x' * 80 for _ in range(100))
    parts = chunk(text, limit=500)
    assert len(parts) > 1
    assert all(len(p) <= 500 for p in parts)
    assert ''.join(p.replace('\n', '') for p in parts) == text.replace('\n', '')


def test_long_line_is_hard_wrapped():
    parts = chunk('a' * 1200, limit=500)
    assert [len(p) for p in parts] == [500, 500, 200]


def test_code_fence_is_closed_and_reopened():
    text = '```python\n' + 'print(1)\n' * 200 + '```'
    parts = chunk(text, limit=400)
    assert parts[0].endswith('\n```')
    assert parts[1].startswith('```python\n')
    for p in parts:
        assert p.count('```') % 2 == 0


def test_anon_is_stable_and_short():
    assert anon(123) == anon(123)
    assert anon(123) != anon(124)
    assert len(anon(123)) == 10


def test_rate_limiter_per_user_window():
    now = [0.0]
    rl = RateLimiter(per_hour=2, per_day=100, clock=lambda: now[0])
    assert rl.check(1) is None
    assert rl.check(1) is None
    assert rl.check(1) == 'user'
    assert rl.check(2) is None  # other users are unaffected
    now[0] = 3601
    assert rl.check(1) is None  # the window rolled over


def test_rate_limiter_daily_cap_resets():
    day = [dt.date(2026, 10, 23)]
    rl = RateLimiter(per_hour=100, per_day=2, today=lambda: day[0])
    assert rl.check(1) is None
    assert rl.check(2) is None
    assert rl.check(3) == 'guild'
    day[0] = dt.date(2026, 10, 24)
    assert rl.check(3) is None
