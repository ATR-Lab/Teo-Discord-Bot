"""Things Teo can do on Discord for the person asking: reminders and scheduled events.

Claude calls these as client tools. Each call runs with an `ActionContext` for the message being
answered, so a reminder always belongs to the person who asked, and an event is only created
when that person is allowed to create events.

Reminders live in SQLite in the service's state directory (`$STATE_DIRECTORY`, set by systemd to
/var/lib/teo on the server), so they survive restarts and deploys.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import datetime as dt
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from anthropic.types.beta import BetaToolParam

LAB_TZ = ZoneInfo('America/New_York')
MAX_ACTIVE_PER_USER = 25
MAX_AHEAD = dt.timedelta(days=366)
MIN_AHEAD = dt.timedelta(minutes=1)
MAX_TEXT = 300


def now() -> dt.datetime:
    """Return the current time in UTC."""
    return dt.datetime.now(dt.UTC)


def parse_when(value: str) -> dt.datetime:
    """Parse an ISO 8601 date-time; a time without an offset is lab time (America/New_York).

    Raises:
        ValueError: If the value is not ISO 8601.
    """
    when = dt.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if when.tzinfo is None:
        when = when.replace(tzinfo=LAB_TZ)
    return when.astimezone(dt.UTC)


def lab_time(when: dt.datetime) -> str:
    """Format a time for people in the lab, for example 'Fri, Nov 13, 2026, 5:00 PM EST'."""
    t = when.astimezone(LAB_TZ)
    return t.strftime('%a, %b %d, %Y, ') + t.strftime('%I:%M %p %Z').lstrip('0')


@dataclass(frozen=True)
class Reminder:
    """One stored reminder."""

    id: int
    user_id: int
    channel_id: int
    fire_at: dt.datetime
    text: str
    jump_url: str


class ReminderStore:
    """SQLite-backed reminders.

    Args:
        path: Database file, or ':memory:' for tests.
    """

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS reminders ('
            ' id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,'
            ' channel_id INTEGER NOT NULL, fire_at TEXT NOT NULL, text TEXT NOT NULL,'
            ' jump_url TEXT NOT NULL, created_at TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0)'
        )
        self.db.commit()

    @staticmethod
    def _row(r: tuple[Any, ...]) -> Reminder:
        return Reminder(r[0], r[1], r[2], dt.datetime.fromisoformat(r[3]), r[4], r[5])

    def add(
        self, user_id: int, channel_id: int, fire_at: dt.datetime, text: str, jump_url: str
    ) -> int:
        """Store a reminder and return its id."""
        cur = self.db.execute(
            'INSERT INTO reminders (user_id, channel_id, fire_at, text, jump_url, created_at)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, channel_id, fire_at.isoformat(), text, jump_url, now().isoformat()),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    def pending(self, user_id: int) -> list[Reminder]:
        """List a user's reminders that have not been sent, soonest first."""
        rows = self.db.execute(
            'SELECT id, user_id, channel_id, fire_at, text, jump_url FROM reminders'
            ' WHERE user_id = ? AND sent = 0 ORDER BY fire_at',
            (user_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def due(self, at: dt.datetime) -> list[Reminder]:
        """List every unsent reminder whose time has come."""
        rows = self.db.execute(
            'SELECT id, user_id, channel_id, fire_at, text, jump_url FROM reminders'
            ' WHERE sent = 0 AND fire_at <= ? ORDER BY fire_at',
            (at.isoformat(),),
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_sent(self, reminder_id: int) -> None:
        """Mark a reminder delivered."""
        self.db.execute('UPDATE reminders SET sent = 1 WHERE id = ?', (reminder_id,))
        self.db.commit()

    def cancel(self, user_id: int, reminder_id: int) -> bool:
        """Delete one of the user's unsent reminders; return whether one was deleted."""
        cur = self.db.execute(
            'DELETE FROM reminders WHERE id = ? AND user_id = ? AND sent = 0',
            (reminder_id, user_id),
        )
        self.db.commit()
        return cur.rowcount > 0


@dataclass
class ActionContext:
    """Who is asking, and where.

    Attributes:
        user_id: The person Teo is answering.
        channel_id: Where the conversation is happening.
        jump_url: Link to the message, shown again when a reminder fires.
        can_create_events: Whether this person may create server events.
        create_event: Callback that creates a scheduled event and returns its link.
        list_events: Callback that describes upcoming scheduled events.
    """

    user_id: int
    channel_id: int
    jump_url: str
    can_create_events: bool
    create_event: Callable[[dict[str, Any]], Awaitable[str]]
    list_events: Callable[[], Awaitable[str]]


def tool_definitions() -> list[BetaToolParam]:
    """Return the action tools, in a fixed order (they are part of the cached prompt)."""
    when = {
        'type': 'string',
        'description': 'ISO 8601 date-time with a UTC offset, for example '
        '2026-11-13T17:00:00-05:00. Resolve relative dates ("next Friday at 5") from the '
        'current time given in the question.',
    }
    return [
        {
            'name': 'set_reminder',
            'description': 'Set a reminder for the person asking. At that time Teo posts the '
            'reminder in this channel and mentions them. Only for the asker; never for other '
            'people or roles.',
            'strict': True,
            'input_schema': {
                'type': 'object',
                'properties': {
                    'when': when,
                    'message': {
                        'type': 'string',
                        'description': 'What to remind them about, short, in their words.',
                    },
                },
                'required': ['when', 'message'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'list_my_reminders',
            'description': "List the asker's upcoming reminders with their ids.",
            'strict': True,
            'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
        {
            'name': 'cancel_reminder',
            'description': "Cancel one of the asker's upcoming reminders by id.",
            'strict': True,
            'input_schema': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}},
                'required': ['id'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'create_server_event',
            'description': 'Create a scheduled event on the ATR Lab Discord server (shows in '
            'the Events list; members can mark Interested). Only works if the asker may '
            'create events. Use it only when the name, start time and place are clear from '
            'the conversation; never invent a room, time or link. For an online event in a '
            'voice channel give voice_channel_id; otherwise give location.',
            'strict': True,
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'Event title, under 100 characters.',
                    },
                    'start': when,
                    'end': {**when, 'description': 'End time. Required for in-person events.'},
                    'location': {
                        'type': 'string',
                        'description': 'Place or link for an in-person or external event.',
                    },
                    'voice_channel_id': {
                        'type': 'string',
                        'description': 'Id of a voice channel for an online event.',
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Details, up to 1000 characters.',
                    },
                },
                'required': ['name', 'start'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'list_server_events',
            'description': 'List upcoming scheduled events on the server.',
            'strict': True,
            'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
    ]


ACTION_NAMES = frozenset(t['name'] for t in tool_definitions())


class Actions:
    """Runs action tools for one context.

    Args:
        store: Reminder storage.
    """

    def __init__(self, store: ReminderStore) -> None:
        self.store = store

    async def run(self, name: str, args: dict[str, Any], ctx: ActionContext) -> tuple[str, bool]:
        """Run one tool call and return (result text, is_error)."""
        try:
            if name == 'set_reminder':
                return self.set_reminder(args, ctx)
            if name == 'list_my_reminders':
                return self.list_reminders(ctx), False
            if name == 'cancel_reminder':
                ok = self.store.cancel(ctx.user_id, int(args.get('id', 0)))
                return (
                    'Cancelled.' if ok else 'No upcoming reminder of theirs with that id.'
                ), not ok
            if name == 'list_server_events':
                return await ctx.list_events(), False
            if name == 'create_server_event':
                if not ctx.can_create_events:
                    return (
                        'Not allowed: only members with the Researcher role may create server '
                        'events. Suggest they ask a lab researcher to add it.',
                        True,
                    )
                return await ctx.create_event(args), False
        except ValueError as e:
            return f'Invalid input: {e}', True
        return f'Unknown action {name}.', True

    def set_reminder(self, args: dict[str, Any], ctx: ActionContext) -> tuple[str, bool]:
        """Validate and store a reminder for the asker."""
        when = parse_when(str(args.get('when', '')))
        text = str(args.get('message', '')).strip()[:MAX_TEXT]
        if not text:
            return 'The reminder needs a message.', True
        delta = when - now()
        if delta < MIN_AHEAD:
            return 'That time is in the past or less than a minute away.', True
        if delta > MAX_AHEAD:
            return 'Reminders can be at most a year ahead.', True
        if len(self.store.pending(ctx.user_id)) >= MAX_ACTIVE_PER_USER:
            return f'They already have {MAX_ACTIVE_PER_USER} upcoming reminders.', True
        rid = self.store.add(ctx.user_id, ctx.channel_id, when, text, ctx.jump_url)
        return f'Reminder #{rid} set for {lab_time(when)} in this channel.', False

    def list_reminders(self, ctx: ActionContext) -> str:
        """Describe the asker's upcoming reminders."""
        items = self.store.pending(ctx.user_id)
        if not items:
            return 'No upcoming reminders.'
        return '\n'.join(f'#{r.id}: {lab_time(r.fire_at)}: {r.text}' for r in items)
