from teo.config import Settings


def test_defaults(monkeypatch):
    for k in ('TEO_GUILD_ID', 'TEO_MODEL', 'TEO_EFFORT'):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.guild_id == 809126702038646808
    assert s.model == 'claude-opus-5-5'
    assert s.effort == 'low'


def test_env_overrides(monkeypatch):
    monkeypatch.setenv('TEO_MODEL', 'claude-haiku-5-5')
    monkeypatch.setenv('TEO_USER_PER_HOUR', '5')
    s = Settings.from_env()
    assert s.model == 'claude-haiku-5-5'
    assert s.user_per_hour == 5
