# Teo-Discord-Bot

Teo, the ATR Lab's Discord assistant: a discord.py client (`teo/bot.py`) that answers with Claude
(`teo/brain.py`) using the lab's docs repositories (`teo/docs.py`). Read `README.md` first.

## Commands
- Setup: `uv sync`
- Check everything (what CI runs): `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest`
- Format: `uv run ruff format .`
- Run locally: see README → Develop. Stop the AWS copy first (Actions → ops → stop).

## Rules
- Merging to `main` deploys to the live bot. Agents work on a branch and never push to `main`.
- Style: the lab's Python guide (single quotes, 99 columns, Google docstrings, `mypy --strict` on `teo/`).
- `teo/prompt.md` holds only verified lab facts from the ATR-Lab `about` repo. Never fill a `[placeholder]` by guessing.
- Keep the system prompt and tool list byte-stable for the life of the process (prompt caching). Anything that changes per request (date, channel, messages) goes in the user turn.
- Never put tokens, keys or personal data in the repo, a prompt, a log line or a test. Secrets live in AWS SSM under `/atr-teo/`.
- Never let code move a robot or change hardware; Teo only talks.
- Settings go in `deploy/settings.env`; infrastructure scripts in `deploy/` are idempotent and documented at their top.
