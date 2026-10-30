import datetime as dt

from teo.actions import (
    MAX_ACTIVE_PER_USER,
    ActionContext,
    Actions,
    ReminderStore,
    lab_time,
    now,
    parse_when,
)


def ctx(user=1, can_events=False, created=None):
    async def create(args):
        (created if created is not None else []).append(args)
        return 'Created "x": https://discord.com/events/1/2.'

    async def listing():
        return 'No upcoming events.'

    return ActionContext(
        user, 10, 'https://discord.com/channels/1/10/99', can_events, create, listing
    )


def iso(delta):
    return (now() + delta).isoformat()


def test_parse_when_assumes_lab_time_and_accepts_z():
    naive = parse_when('2026-11-13T17:00:00')
    assert naive == dt.datetime(2026, 11, 13, 22, 0, tzinfo=dt.UTC)  # 5 PM EST = 22:00 UTC
    assert parse_when('2026-11-13T12:00:00Z').hour == 12
    assert 'EST' in lab_time(naive) and '5:00 PM' in lab_time(naive)


def test_store_round_trip_and_due():
    s = ReminderStore(':memory:')
    soon = now() + dt.timedelta(minutes=5)
    rid = s.add(1, 10, soon, 'submit the paper', 'url')
    assert [r.id for r in s.pending(1)] == [rid]
    assert s.due(now()) == []
    due = s.due(soon + dt.timedelta(seconds=1))
    assert [r.text for r in due] == ['submit the paper']
    s.mark_sent(rid)
    assert s.pending(1) == [] and s.due(soon + dt.timedelta(days=1)) == []


async def test_set_list_and_cancel_reminder():
    a = Actions(ReminderStore(':memory:'))
    text, err = await a.run(
        'set_reminder', {'when': iso(dt.timedelta(days=3)), 'message': 'HRI paper'}, ctx()
    )
    assert not err and text.startswith('Reminder #1 set for')
    text, _ = await a.run('list_my_reminders', {}, ctx())
    assert 'HRI paper' in text
    _, err = await a.run('cancel_reminder', {'id': 1}, ctx(user=2))  # someone else's
    assert err
    text, err = await a.run('cancel_reminder', {'id': 1}, ctx())
    assert not err and text == 'Cancelled.'


async def test_reminder_limits():
    a = Actions(ReminderStore(':memory:'))
    _, err = await a.run(
        'set_reminder', {'when': iso(-dt.timedelta(hours=1)), 'message': 'x'}, ctx()
    )
    assert err
    _, err = await a.run(
        'set_reminder', {'when': iso(dt.timedelta(days=400)), 'message': 'x'}, ctx()
    )
    assert err
    _, err = await a.run('set_reminder', {'when': 'next friday', 'message': 'x'}, ctx())
    assert err
    for i in range(MAX_ACTIVE_PER_USER):
        _, err = await a.run(
            'set_reminder', {'when': iso(dt.timedelta(days=1)), 'message': f'{i}'}, ctx()
        )
        assert not err
    text, err = await a.run(
        'set_reminder', {'when': iso(dt.timedelta(days=1)), 'message': 'one more'}, ctx()
    )
    assert err and 'already' in text


async def test_events_need_permission():
    created = []
    a = Actions(ReminderStore(':memory:'))
    args = {'name': 'Lab meeting', 'start': iso(dt.timedelta(days=1)), 'location': 'MSB'}
    text, err = await a.run('create_server_event', args, ctx(can_events=False, created=created))
    assert err and 'Not allowed' in text and created == []
    text, err = await a.run('create_server_event', args, ctx(can_events=True, created=created))
    assert not err and created == [args]
    text, _ = await a.run('list_server_events', {}, ctx())
    assert text == 'No upcoming events.'
