# Teo: the ATR Lab Discord assistant

Teo ("teleoperator") is the assistant bot of the Advanced Telerobotics Research Lab Discord server at Kent State
University. It answers questions about robotics, code, ROS 2, lab safety and the lab's documentation, using Claude
(Anthropic API) and the lab's public docs repositories.

## What it does

- **Triggers:** an @mention, a reply to one of Teo's messages, `/ask` (optionally private), or a new post in the
  help-desk forum (first answer only). DMs get a one-line pointer back to the server.
- **Knowledge:** a persona and verified-facts system prompt (`teo/prompt.md`), a map of the channels a Verified member
  can see, the `lab_docs` tool over [about](https://github.com/ATR-Lab/about),
  [getting-started-atr-lab](https://github.com/ATR-Lab/getting-started-atr-lab) and
  [dev-guidelines](https://github.com/ATR-Lab/dev-guidelines) (branch `docs/revamp` first, then the default branch),
  plus Claude's web search and web fetch.
- **Context:** the reply chain and the last 12 messages in the channel, sent as a plain-text transcript.
- **Limits:** 20 questions per person per hour, 500 per day for the server (`deploy/teo.env.example`).
- **Privacy:** Teo logs token counts and a hashed user id, never message text.

## Model and cost

`claude-opus-5-5` at effort `low`, with server-side refusal fallback (`fallbacks: "default"`). The system prompt and
tools (about 10,000 tokens) are cached for an hour, so a typical answer costs about 1 to 3 cents. To trade quality for
cost, set `TEO_MODEL=claude-haiku-5-5` (or `claude-sonnet-5-5`) in `deploy/teo.env.example` and redeploy.

## Run locally

```bash
python3 -m venv ~/Active/.venvs/atr-teo && ~/Active/.venvs/atr-teo/bin/pip install -r requirements.txt
DISCORD_BOT_TOKEN=$(get-key DISCORD_BOT_TOKEN) ANTHROPIC_API_KEY=$(get-key ANTHROPIC_API_KEY_ATR_LAB_DISCORD) \
  TEO_HELP_FORUM_ID=1563328209444016332 ~/Active/.venvs/atr-teo/bin/python -m teo
```

Stop the AWS copy first (`systemctl stop teo` over SSM), or both will answer.

## Hosting (AWS, us-east-2)

One `t4g.micro` Amazon Linux 2023 instance named `atr-teo`, managed through Systems Manager (no SSH, no inbound
rules). Secrets live in SSM Parameter Store (`/atr-teo/DISCORD_BOT_TOKEN`, `/atr-teo/ANTHROPIC_API_KEY`) and are read
at start by `deploy/run.sh`. Releases go through the private bucket `atr-teo-deploy-<account>`.

| Task | Command |
|---|---|
| First-time setup | `DISCORD_BOT_TOKEN=... ANTHROPIC_API_KEY=... deploy/provision.sh` |
| Ship the current code and settings | `deploy/deploy.sh` |
| Use a specific AWS identity | prefix either script with `AWS_CLI=<wrapper or "aws --profile X">` |
| Logs | `aws ssm start-session --target <instance>` then `journalctl -u teo -f` |

Running cost is about $7 a month for the instance and disk, plus Anthropic usage.

## Files

| Path | What it is |
|---|---|
| `teo/bot.py` | Discord client: triggers, context, rate limits, `/ask` and `/about-teo` |
| `teo/brain.py` | Claude request and the short tool loop |
| `teo/docs.py` | Index and cached reads of the lab's docs repositories |
| `teo/prompt.md` | Persona, rules, verified lab facts |
| `deploy/` | Provisioning, deploy, instance install script, systemd unit, settings |
