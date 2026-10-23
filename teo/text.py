"""Pure helpers with no Discord or network dependencies (easy to unit test)."""

from collections import defaultdict, deque
from collections.abc import Callable
import datetime as dt
import hashlib
import re
import time

DISCORD_LIMIT = 2000
_FENCE = re.compile(r'^```(\S*)', flags=re.M)


def anon(user_id: int) -> str:
    """Return a short, stable hash of a Discord user id for logs."""
    return hashlib.sha256(f'teo:{user_id}'.encode()).hexdigest()[:10]


def chunk(text: str, limit: int = DISCORD_LIMIT - 10) -> list[str]:
    """Split a reply into Discord-sized messages.

    Splits on line boundaries where possible, hard-wraps lines longer than the limit, and keeps
    fenced code blocks balanced: a block cut by a split is closed at the end of one part and
    reopened, with the same language tag, at the start of the next.

    Args:
        text: The full reply.
        limit: Maximum characters per part before fences are added.

    Returns:
        One or more non-empty parts.
    """
    parts: list[str] = []
    cur = ''
    for line in text.split('\n'):
        if len(line) > limit and cur:
            parts.append(cur)
            cur = ''
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            parts.append(cur)
            cur = ''
        cur = f'{cur}\n{line}' if cur else line
    if cur:
        parts.append(cur)

    out: list[str] = []
    fence: str | None = None
    for p in parts:
        if fence:
            p = f'{fence}\n{p}'
        opens = _FENCE.findall(p)
        if len(opens) % 2:
            fence = '```' + opens[-1]
            p += '\n```'
        else:
            fence = None
        out.append(p)
    return out or ['']


class RateLimiter:
    """Per-user hourly and server-wide daily request limits, kept in memory.

    Args:
        per_hour: Requests one user may make in any rolling hour.
        per_day: Requests the whole server may make per calendar day.
        clock: Time source in seconds (injectable for tests).
        today: Date source (injectable for tests).
    """

    def __init__(
        self,
        per_hour: int,
        per_day: int,
        clock: Callable[[], float] = time.time,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.per_hour = per_hour
        self.per_day = per_day
        self._clock = clock
        self._today = today
        self._users: defaultdict[int, deque[float]] = defaultdict(deque)
        self._day = today()
        self._count = 0

    def check(self, user_id: int) -> str | None:
        """Record a request if it is allowed.

        Returns:
            None when allowed, 'user' when this user hit the hourly limit, or 'guild' when the
            server hit the daily limit.
        """
        now = self._clock()
        if self._today() != self._day:
            self._day, self._count = self._today(), 0
        q = self._users[user_id]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= self.per_hour:
            return 'user'
        if self._count >= self.per_day:
            return 'guild'
        q.append(now)
        self._count += 1
        return None
