"""Runtime settings, read once from the environment."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Everything Teo reads from the environment.

    Secrets (`DISCORD_BOT_TOKEN`, `ANTHROPIC_API_KEY`) are read where they are used and never
    stored here, so a settings object is safe to log.
    """

    guild_id: int = 809126702038646808
    help_forum_id: int = 0
    model: str = 'claude-opus-5-5'
    effort: str = 'low'
    max_tokens: int = 8000
    user_per_hour: int = 20
    guild_per_day: int = 500
    context_messages: int = 12

    @classmethod
    def from_env(cls) -> 'Settings':
        """Build settings from `TEO_*` environment variables, falling back to the defaults."""
        d = cls()
        env = os.environ.get
        return cls(
            guild_id=int(env('TEO_GUILD_ID', d.guild_id)),
            help_forum_id=int(env('TEO_HELP_FORUM_ID', d.help_forum_id)),
            model=env('TEO_MODEL', d.model),
            effort=env('TEO_EFFORT', d.effort),
            max_tokens=int(env('TEO_MAX_TOKENS', d.max_tokens)),
            user_per_hour=int(env('TEO_USER_PER_HOUR', d.user_per_hour)),
            guild_per_day=int(env('TEO_GUILD_PER_DAY', d.guild_per_day)),
            context_messages=int(env('TEO_CONTEXT_MESSAGES', d.context_messages)),
        )
