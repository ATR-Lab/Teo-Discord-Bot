#!/bin/bash
# Runs on the instance (as root, via SSM): install or update Teo from the release tarball in S3.
set -euo pipefail
BUCKET="$1"; REGION="$2"
id teo >/dev/null 2>&1 || useradd --system --home /opt/teo --shell /sbin/nologin teo
command -v python3.12 >/dev/null || dnf install -y -q python3.12 python3.12-pip
mkdir -p /opt/teo
aws s3 cp --region "$REGION" "s3://$BUCKET/teo.tar.gz" /tmp/teo.tar.gz
rm -rf /opt/teo/app.new && mkdir -p /opt/teo/app.new && tar -xzf /tmp/teo.tar.gz -C /opt/teo/app.new
[ -d /opt/teo/venv ] || python3.12 -m venv /opt/teo/venv
/opt/teo/venv/bin/pip install -q --upgrade pip
/opt/teo/venv/bin/pip install -q -r /opt/teo/app.new/requirements.txt
rm -rf /opt/teo/app && mv /opt/teo/app.new /opt/teo/app
install -m 0755 /opt/teo/app/deploy/run.sh /opt/teo/run.sh
install -m 0644 /opt/teo/app/deploy/teo.service /etc/systemd/system/teo.service
aws s3 cp --region "$REGION" "s3://$BUCKET/teo.env" /etc/teo.env && chmod 0644 /etc/teo.env
chown -R teo:teo /opt/teo
systemctl daemon-reload
systemctl enable teo >/dev/null 2>&1
systemctl restart teo
sleep 8
systemctl is-active teo
journalctl -u teo -n 5 --no-pager
