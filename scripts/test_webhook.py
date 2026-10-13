#!/usr/bin/env python3
"""Locally exercise /webhook/keycrm against a running server."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from server import load_dotenv  # noqa: E402

load_dotenv()
PORT = os.getenv("PORT", "8787")
BASE = f"http://127.0.0.1:{PORT}"


def post(path: str, body: dict) -> dict:
    raw = json.dumps(body).encode("utf-8")
    req = Request(
        f"{BASE}{path}",
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path: str) -> dict:
    with urlopen(f"{BASE}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    print("health:", get("/health"))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "event": "lead.change_lead_status",
        "context": {
            "id": 47,
            "title": "Форма лиды 2026",
            "contact_id": 64,
            "manager_id": None,
            "source_id": 1,
            "status_id": 1,
            "pipeline_id": 1,
            "status_changed_at": now,
            "created_at": now,
            "updated_at": now,
            "manager_comment": "Тест webhook локально",
            "is_finished": False,
        },
    }
    print("webhook:", json.dumps(post("/webhook/keycrm", payload), ensure_ascii=False, indent=2))

    skip = {
        "event": "lead.change_lead_status",
        "context": {
            **payload["context"],
            "status_id": 12,
            "created_at": "2026-01-01T00:00:00.000000Z",
            "status_changed_at": now,
        },
    }
    print("skip:", json.dumps(post("/webhook/keycrm", skip), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
