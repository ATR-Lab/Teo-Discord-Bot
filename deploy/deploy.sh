#!/bin/bash
# Ship the current checkout to the instance: release tarball to S3, then install.sh over SSM.
# Exits non-zero if the install fails or Teo does not come up (install.sh rolls back).
# Usage: deploy/deploy.sh            (AWS_CLI may name a wrapper; TEO_VERSION overrides the label)
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
A() { $AWS_CLI --region "$REGION" "$@"; }
ID=$(A ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
[ "$ID" != "None" ] || { echo "no running $NAME instance; run deploy/provision.sh first" >&2; exit 1; }

VERSION="${TEO_VERSION:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/src"
cp -R teo deploy pyproject.toml uv.lock .python-version README.md "$TMP/src/"
echo "$VERSION" > "$TMP/src/VERSION"
find "$TMP/src" -name __pycache__ -prune -exec rm -rf {} +
# macOS bsdtar adds extended attributes that GNU tar on the instance warns about.
TAR_FLAGS=(); tar --version | grep -q bsdtar && TAR_FLAGS=(--no-xattrs --no-mac-metadata)
COPYFILE_DISABLE=1 tar "${TAR_FLAGS[@]}" -C "$TMP/src" -czf "$TMP/teo.tar.gz" .
A s3 cp --quiet "$TMP/teo.tar.gz" "s3://$BUCKET/teo.tar.gz"
A s3 cp --quiet deploy/install.sh "s3://$BUCKET/install.sh"

echo "deploying $VERSION to $ID"
CMD=$(A ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript \
  --comment "deploy teo $VERSION" --timeout-seconds 600 \
  --parameters "commands=[\"aws s3 cp --quiet --region $REGION s3://$BUCKET/install.sh /tmp/install.sh\",\"bash /tmp/install.sh $BUCKET $REGION\"]" \
  --query Command.CommandId --output text)
A ssm wait command-executed --command-id "$CMD" --instance-id "$ID" 2>/dev/null || true
read -r STATUS < <(A ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query Status --output text)
A ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" \
  --query '[StandardOutputContent,StandardErrorContent]' --output text | grep -v '^None$' | tail -40
echo "status: $STATUS"
[ "$STATUS" = "Success" ]
