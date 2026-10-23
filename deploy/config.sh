# Shared settings for provision.sh and deploy.sh. AWS_CLI lets you point at a wrapper or profile.
AWS_CLI="${AWS_CLI:-aws}"
REGION="${REGION:-us-east-2}"
NAME=atr-teo
ACCOUNT="$($AWS_CLI sts get-caller-identity --query Account --output text)"
BUCKET="${NAME}-deploy-${ACCOUNT}"
