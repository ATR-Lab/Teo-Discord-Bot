#!/bin/bash
# Ship the current tree to the instance: tarball + env file to S3, then install.sh over SSM.
set -euo pipefail
cd "$(dirname "$0")/.."; source deploy/config.sh
A() { $AWS_CLI --region "$REGION" "$@"; }
ID=$(A ec2 describe-instances --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
[ "$ID" != "None" ] || { echo "no running $NAME instance; run deploy/provision.sh first" >&2; exit 1; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='__pycache__' --exclude='.git' --exclude='.venv' -czf "$TMP/teo.tar.gz" teo deploy requirements.txt
{ echo "AWS_REGION=$REGION"
  grep -v '^#' deploy/teo.env.example | grep '=' ; } > "$TMP/teo.env"
A s3 cp --quiet "$TMP/teo.tar.gz" "s3://$BUCKET/teo.tar.gz"
A s3 cp --quiet "$TMP/teo.env" "s3://$BUCKET/teo.env"
A s3 cp --quiet deploy/install.sh "s3://$BUCKET/install.sh"

CMD=$(A ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript --comment "deploy teo" \
  --parameters "commands=[\"aws s3 cp --region $REGION s3://$BUCKET/install.sh /tmp/install.sh\",\"bash /tmp/install.sh $BUCKET $REGION\"]" \
  --query Command.CommandId --output text)
A ssm wait command-executed --command-id "$CMD" --instance-id "$ID" || true
A ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | tail -20
