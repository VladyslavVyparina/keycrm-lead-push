#!/usr/bin/env bash
# Deploy to server and install systemd service.
# Usage: ./deploy/remote_setup.sh
set -euo pipefail

HOST="${DEPLOY_HOST:-173.242.54.197}"
USER="${DEPLOY_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/opt/keycrm-lead-push}"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Sync to ${USER}@${HOST}:${REMOTE_DIR}"
ssh -o StrictHostKeyChecking=accept-new "${USER}@${HOST}" "mkdir -p '${REMOTE_DIR}'"
rsync -avz --delete \
  --exclude '.git' \
  --exclude 'logs/*.log' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  "${LOCAL_DIR}/" "${USER}@${HOST}:${REMOTE_DIR}/"

echo "==> Install systemd service"
ssh "${USER}@${HOST}" bash -s <<EOF
set -euo pipefail
cp '${REMOTE_DIR}/deploy/keycrm-lead-push.service' /etc/systemd/system/keycrm-lead-push.service
# open firewall port if ufw exists
if command -v ufw >/dev/null 2>&1; then
  ufw allow 8787/tcp || true
fi
# firewalld
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=8787/tcp || true
  firewall-cmd --reload || true
fi
systemctl daemon-reload
systemctl enable keycrm-lead-push
systemctl restart keycrm-lead-push
sleep 1
systemctl --no-pager status keycrm-lead-push || true
curl -sS "http://127.0.0.1:8787/health" || true
echo
EOF

echo "==> Done"
echo "Webhook URL for KeyCRM: http://${HOST}:8787/webhook/keycrm"
echo "Setup guide:            http://${HOST}:8787/setup"
