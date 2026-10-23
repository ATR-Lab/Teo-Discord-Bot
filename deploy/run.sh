#!/bin/bash
# Pull the two secrets from SSM Parameter Store at start; they live only in this process's environment.
set -euo pipefail
get() { aws ssm get-parameter --region "$AWS_REGION" --with-decryption --name "$1" --query Parameter.Value --output text; }
export DISCORD_BOT_TOKEN="$(get /atr-teo/DISCORD_BOT_TOKEN)"
export ANTHROPIC_API_KEY="$(get /atr-teo/ANTHROPIC_API_KEY)"
exec /opt/teo/venv/bin/python -m teo
