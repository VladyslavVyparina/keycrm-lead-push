#!/usr/bin/env python3
"""Generate deploy/install_on_server.sh with embedded project archive."""

from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy" / "install_on_server.sh"

FILES = [
    "src/server.py",
    "scripts/test_api.py",
    "scripts/test_webhook.py",
    "deploy/keycrm-lead-push.service",
    "README.md",
    ".env",
    ".gitignore",
]


def main() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in FILES:
            path = ROOT / rel
            if path.exists():
                tar.add(path, arcname=rel)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    script = f"""#!/usr/bin/env bash
# One-shot install for KeyCRM lead webhook on this VPS.
# Run in Termius as root:
#   bash install_on_server.sh
set -euo pipefail

APP_DIR=/opt/keycrm-lead-push
echo "==> Installing into $APP_DIR"

mkdir -p "$APP_DIR"
cd "$APP_DIR"

python3 - <<'PY'
import base64, tarfile, io
payload = \"\"\"{b64}\"\"\"
data = base64.b64decode(payload)
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
    tar.extractall(".")
print("files extracted")
PY

chmod 600 "$APP_DIR/.env" || true
cp "$APP_DIR/deploy/keycrm-lead-push.service" /etc/systemd/system/keycrm-lead-push.service

if command -v ufw >/dev/null 2>&1; then
  ufw allow 8787/tcp || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=8787/tcp || true
  firewall-cmd --reload || true
fi

systemctl daemon-reload
systemctl enable keycrm-lead-push
systemctl restart keycrm-lead-push
sleep 1
systemctl --no-pager --full status keycrm-lead-push || true
echo
echo "==> Health:"
curl -sS http://127.0.0.1:8787/health || true
echo
echo
echo "DONE"
echo "Webhook for KeyCRM: http://173.242.54.197:8787/webhook/keycrm"
echo "Method: POST"
echo "Also set native trigger Create Task for push in KeyCRM app (see README)."
"""
    OUT.write_text(script, encoding="utf-8")
    OUT.chmod(0o755)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
