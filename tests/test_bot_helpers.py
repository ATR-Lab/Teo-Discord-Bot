from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import discord
import pytest

from teo.bot import Teo, category_id_of
from teo.config import Settings


def test_category_of_plain_channel():
    assert category_id_of(SimpleNamespace(category_id=7)) == 7
    assert category_id_of(SimpleNamespace(category_id=None)) is None
    assert category_id_of(object()) is None


def test_category_of_thread_uses_parent():
    thread = discord.Thread.__new__(discord.Thread)
    thread.parent_id = 1
    thread.guild = SimpleNamespace(get_channel=lambda _id: SimpleNamespace(category_id=9))
    assert category_id_of(thread) == 9


RESEARCHER = 809299070137008158
GUILD = 809126702038646808


def member(*role_ids, guild_id=GUILD, admin=False):
    """A stand-in guild member with the given roles."""
    m = mock.MagicMock(spec=discord.Member)
    m.roles = [SimpleNamespace(id=r) for r in role_ids]
    m.guild = SimpleNamespace(id=guild_id)
    m.guild_permissions = discord.Permissions(administrator=admin, create_events=admin)
    return m


def may(user, role_ids=frozenset({RESEARCHER})):
    bot = SimpleNamespace(settings=Settings(guild_id=GUILD, event_role_ids=role_ids))
    return Teo.may_create_events(bot, user)


def test_only_the_researcher_role_may_create_events():
    assert may(member(RESEARCHER))
    assert may(member(1, RESEARCHER))
    assert not may(member(1, 2))


def test_admin_permission_alone_does_not_count():
    assert not may(member(1, admin=True))


def test_no_configured_roles_means_nobody():
    assert not may(member(RESEARCHER), role_ids=frozenset())


def test_dms_and_other_servers_never_count():
    assert not may(SimpleNamespace(roles=[SimpleNamespace(id=RESEARCHER)]))
    assert not may(member(RESEARCHER, guild_id=1))


def test_deployed_settings_name_only_the_researcher_role():
    env = Path(__file__).resolve().parent.parent / 'deploy' / 'settings.env'
    line = next(x for x in env.read_text().splitlines() if x.startswith('TEO_EVENT_ROLE_IDS='))
    assert line == f'TEO_EVENT_ROLE_IDS={RESEARCHER}'


async def test_role_is_checked_again_just_before_creating():
    removed = member(1)  # lost the Researcher role since asking
    guild = SimpleNamespace(
        fetch_member=mock.AsyncMock(return_value=removed),
        create_scheduled_event=mock.AsyncMock(),
    )
    bot = SimpleNamespace(
        settings=Settings(guild_id=GUILD, event_role_ids=frozenset({RESEARCHER})),
        get_guild=lambda _id: guild,
    )
    bot.may_create_events = lambda user: Teo.may_create_events(bot, user)
    args = {'name': 'Lab social', 'start': '2099-01-01T17:00:00-05:00', 'location': 'MSB'}
    with pytest.raises(ValueError, match='Researcher'):
        await Teo.create_event(bot, args, member(RESEARCHER))
    guild.create_scheduled_event.assert_not_called()
