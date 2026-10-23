#!/bin/bash
# Start Teo. The two secrets are read from SSM Parameter Store and live only in this process.
set -euo pipefail
get() {
  aws ssm get-parameter --region "$AWS_REGION" --with-decryption --name "$1" \
    --query Parameter.Value --output text
}
DISCORD_BOT_TOKEN="$(get /atr-teo/DISCORD_BOT_TOKEN)"
ANTHROPIC_API_KEY="$(get /atr-teo/ANTHROPIC_API_KEY)"
export DISCORD_BOT_TOKEN ANTHROPIC_API_KEY
exec /opt/teo/venv/bin/python -m teo
