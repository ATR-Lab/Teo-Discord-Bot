from types import SimpleNamespace

import discord

from teo.bot import category_id_of


def test_category_of_plain_channel():
    assert category_id_of(SimpleNamespace(category_id=7)) == 7
    assert category_id_of(SimpleNamespace(category_id=None)) is None
    assert category_id_of(object()) is None


def test_category_of_thread_uses_parent():
    thread = discord.Thread.__new__(discord.Thread)
    thread.parent_id = 1
    thread.guild = SimpleNamespace(get_channel=lambda _id: SimpleNamespace(category_id=9))
    assert category_id_of(thread) == 9
