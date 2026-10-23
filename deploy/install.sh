#!/bin/bash
# Runs on the instance as root (sent by deploy.sh over SSM): install or update Teo from the
# release in S3, then restart the service. Usage: install.sh <bucket> <region>
set -euo pipefail
BUCKET="$1"; REGION="$2"
id teo >/dev/null 2>&1 || useradd --system --home /opt/teo --shell /sbin/nologin teo
command -v python3.12 >/dev/null || dnf install -y -q python3.12
mkdir -p /opt/teo
[ -x /opt/teo/tools/bin/uv ] || { python3.12 -m venv /opt/teo/tools && /opt/teo/tools/bin/pip install -q uv; }

aws s3 cp --quiet --region "$REGION" "s3://$BUCKET/teo.tar.gz" /tmp/teo.tar.gz
rm -rf /opt/teo/app.new && mkdir -p /opt/teo/app.new
tar -xzf /tmp/teo.tar.gz -C /opt/teo/app.new
# Same locked versions as CI; the project itself runs from its source tree.
(cd /opt/teo/app.new && UV_PROJECT_ENVIRONMENT=/opt/teo/venv UV_PYTHON=python3.12 \
  /opt/teo/tools/bin/uv sync --frozen --no-dev --no-install-project -q)
rm -rf /opt/teo/app.prev; [ -d /opt/teo/app ] && mv /opt/teo/app /opt/teo/app.prev
mv /opt/teo/app.new /opt/teo/app
install -m 0755 /opt/teo/app/deploy/run.sh /opt/teo/run.sh
install -m 0644 /opt/teo/app/deploy/teo.service /etc/systemd/system/teo.service
install -m 0644 /opt/teo/app/deploy/settings.env /etc/teo.env
{ echo "AWS_REGION=$REGION"; echo "TEO_VERSION=$(cat /opt/teo/app/VERSION 2>/dev/null || echo unknown)"; } >> /etc/teo.env
chown -R teo:teo /opt/teo
systemctl daemon-reload
systemctl enable -q teo
START="$(date '+%Y-%m-%d %H:%M:%S')"
systemctl restart teo

# Healthy means the service stays up and logs "ready" within 60 s; otherwise roll back.
for _ in $(seq 1 30); do
  if journalctl -u teo --since "$START" -o cat | grep -q ' ready as '; then
    echo "teo $(grep TEO_VERSION /etc/teo.env | cut -d= -f2) is up"; exit 0
  fi
  sleep 2
done
echo "teo did not report ready; recent log:" >&2
journalctl -u teo -n 30 --no-pager -o cat >&2
if [ -d /opt/teo/app.prev ]; then
  echo "rolling back to the previous release" >&2
  rm -rf /opt/teo/app && mv /opt/teo/app.prev /opt/teo/app
  (cd /opt/teo/app && UV_PROJECT_ENVIRONMENT=/opt/teo/venv UV_PYTHON=python3.12 \
    /opt/teo/tools/bin/uv sync --frozen --no-dev --no-install-project -q)
  install -m 0644 /opt/teo/app/deploy/settings.env /etc/teo.env
  { echo "AWS_REGION=$REGION"; echo "TEO_VERSION=$(cat /opt/teo/app/VERSION 2>/dev/null || echo unknown)"; } >> /etc/teo.env
  systemctl restart teo
fi
exit 1
