# atr-lab-teo-bot

- Location: `/Volumes/MARCUS-PROJECTS/projects/ai-agents/atr-lab-teo-bot` (category: ai-agents)
- Remote: none (local-only repo)
- Stack: Python (create .venv locally; never commit it)
- Start with: `README.md`

## Working here
- Machine-wide rules and layout: `~/AGENTS.md`. Category conventions: `/Volumes/MARCUS-PROJECTS/projects/AGENTS.md`.
- Build output stays on the Mac and is gitignored. Secrets (`.env`) live on MARCUS-PII under `credentials/project-env/`; copy in, never commit.
- Heavy builds: `project-checkout ai-agents/atr-lab-teo-bot` into `~/Active` first.

## Project rules
- Teo is live on AWS (instance `atr-teo`, us-east-2). Ship changes with `deploy/deploy.sh`; don't run a local copy at the same time or both answer.
- AWS identity on this Mac: the `Claude_Agent` IAM user; its keys are in MARCUS-PII (`credentials/api-keys/Claude_Agent_accessKeys.csv`). Use a wrapper that reads them into the environment and pass it as `AWS_CLI`; never print them.
- Secrets: `DISCORD_BOT_TOKEN` and `ANTHROPIC_API_KEY_ATR_LAB_DISCORD` via `get-key`; on AWS they are SSM SecureStrings under `/atr-teo/`.
- `teo/prompt.md` holds only verified lab facts. Take facts from the ATR-Lab `about` repo; never fill a `[placeholder]` from there by guessing.
- Keep the system prompt and tool list byte-stable within a process (prompt caching). Volatile data (date, channel, messages) goes in the user turn.
- Check after a change: `python -m py_compile teo/*.py`, then a short local run (`README.md` → Run locally) with the AWS copy stopped.
- Server change logs for the Discord revamp: `/Volumes/MARCUS-PROJECTS/_agents/reports/2026-10-23-atr-discord-revamp/`.
