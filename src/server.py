#!/usr/bin/env python3
"""KeyCRM webhook receiver + helpers for new-lead notifications."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "events.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("keycrm-lead-push")


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()

API_URL = os.getenv("KEYCRM_API_URL", "https://openapi.keycrm.app/v1").rstrip("/")
API_KEY = os.getenv("KEYCRM_API_KEY", "")
PORT = int(os.getenv("PORT", "8787"))
NEW_LEAD_MAX_AGE_MINUTES = int(os.getenv("NEW_LEAD_MAX_AGE_MINUTES", "10"))
NEW_LEAD_STATUS_IDS = [
    int(x.strip())
    for x in os.getenv("NEW_LEAD_STATUS_IDS", "1").split(",")
    if x.strip().isdigit()
]


def keycrm_fetch(pathname: str, method: str = "GET", body: Optional[dict] = None) -> Any:
    if not API_KEY:
        raise RuntimeError("KEYCRM_API_KEY is missing")
    url = pathname if pathname.startswith("http") else f"{API_URL}{pathname if pathname.startswith('/') else '/' + pathname}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"KeyCRM {exc.code}: {err_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"KeyCRM network error: {exc}") from exc


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_new_lead_event(context: dict) -> bool:
    if not isinstance(context, dict):
        return False

    status_id = context.get("status_id")
    if NEW_LEAD_STATUS_IDS and status_id is not None:
        try:
            if int(status_id) not in NEW_LEAD_STATUS_IDS:
                return False
        except (TypeError, ValueError):
            return False

    created_at = parse_dt(context.get("created_at"))
    status_changed_at = parse_dt(context.get("status_changed_at"))
    if created_at is None:
        return True

    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_sec = (now - created_at).total_seconds()
    if age_sec > NEW_LEAD_MAX_AGE_MINUTES * 60:
        return False

    if status_changed_at is not None:
        if status_changed_at.tzinfo is None:
            status_changed_at = status_changed_at.replace(tzinfo=timezone.utc)
        if abs((status_changed_at - created_at).total_seconds()) > 120:
            return False

    return True


def enrich_lead(context: dict) -> dict:
    details: dict[str, Any] = {
        "id": context.get("id"),
        "title": context.get("title") or "Без назви",
        "pipeline_id": context.get("pipeline_id"),
        "status_id": context.get("status_id"),
        "manager_id": context.get("manager_id"),
        "contact_id": context.get("contact_id"),
        "created_at": context.get("created_at"),
        "manager_comment": context.get("manager_comment") or "",
    }
    try:
        card = keycrm_fetch(f"/pipelines/cards/{context['id']}")
        if isinstance(card, dict):
            details["title"] = card.get("title") or details["title"]
            details["manager_comment"] = card.get("manager_comment") or details["manager_comment"]
            contact_id = card.get("contact_id")
            if contact_id:
                buyer = keycrm_fetch(f"/buyer/{contact_id}")
                if isinstance(buyer, dict):
                    phones = buyer.get("phones") or []
                    phone = buyer.get("phone") or (phones[0] if phones else None)
                    full_name = buyer.get("full_name") or " ".join(
                        x for x in [buyer.get("first_name"), buyer.get("last_name")] if x
                    )
                    details["contact"] = {
                        "id": buyer.get("id"),
                        "full_name": full_name,
                        "phone": phone,
                        "email": buyer.get("email"),
                    }
    except Exception as exc:  # noqa: BLE001
        details["enrich_error"] = str(exc)
    return details


def build_message(lead: dict) -> str:
    contact = lead.get("contact") or {}
    parts = [
        "🔔 Новий лід у воронці KeyCRM",
        "Потрібно звʼязатись!",
        "",
        f"📋 {lead.get('title')}",
        f"ID: {lead.get('id')}",
    ]
    if contact.get("full_name"):
        parts.append(f"👤 {contact['full_name']}")
    if contact.get("phone"):
        parts.append(f"📞 {contact['phone']}")
    if lead.get("manager_comment"):
        parts.append(f"💬 {lead['manager_comment']}")
    return "\n".join(parts)


def notify_telegram(text: str) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"sent": False, "reason": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    req = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            return {"sent": False, "reason": data.get("description", "unknown")}
        return {"sent": True, "message_id": (data.get("result") or {}).get("message_id")}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": str(exc)}


def setup_payload() -> dict:
    pipelines = keycrm_fetch("/pipelines")
    users = keycrm_fetch("/users?limit=50")
    statuses = keycrm_fetch("/pipelines/1/statuses")
    return {
        "ok": True,
        "how_to_get_push_in_keycrm_app": {
            "summary": (
                "OpenAPI не вміє слати push у мобільний додаток KeyCRM. "
                "Push у додаток працює через нативний тригер: новий лід → Створити задачу."
            ),
            "steps": [
                "KeyCRM → Налаштування → Додатково → Автоматизація → Додати тригер",
                "Подія: Воронки → Зміна статусу → «Новий» (status_id=1)",
                "Час: Одразу",
                "Дія: Створити задачу — «Новий лід — звʼязатись»",
                "Відповідальний: адміністратор (хто має отримати push)",
                "Постановщик: ІНШИЙ користувач (якщо той самий — push про створення НЕ прийде)",
                "Профіль адміністратора → Сповіщення → увімкнути PUSH для Завдань",
                "Мобільний додаток KeyCRM → дозволити сповіщення в системі",
            ],
        },
        "account": {
            "pipelines": pipelines.get("data") if isinstance(pipelines, dict) else pipelines,
            "users": [
                {
                    "id": u.get("id"),
                    "full_name": u.get("full_name"),
                    "email": u.get("email"),
                    "role_id": u.get("role_id"),
                }
                for u in ((users or {}).get("data") or [])
            ],
            "pipeline_1_statuses": (statuses or {}).get("data") if isinstance(statuses, dict) else statuses,
            "recommended_trigger": {
                "pipeline": "Ліди (id=1)",
                "status": "Новий (id=1)",
                "assignee_admin": "Гасинець Аліса (id=3)",
                "creator_other_user": "Влад Спеціаліст (id=4)",
            },
        },
        "env": {
            "telegram_configured": bool(
                os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
            ),
            "new_lead_status_ids": NEW_LEAD_STATUS_IDS,
            "new_lead_max_age_minutes": NEW_LEAD_MAX_AGE_MINUTES,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "keycrm-lead-push/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {"raw": raw.decode("utf-8", errors="replace")}

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send(200, {"ok": True, "service": "keycrm-lead-push"})
        if parsed.path == "/setup":
            try:
                return self._send(200, setup_payload())
            except Exception as exc:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": str(exc)})
        if parsed.path == "/webhook/keycrm":
            qs = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            return self._handle_webhook(qs)
        return self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json()
        if parsed.path == "/webhook/keycrm":
            return self._handle_webhook(body)
        if parsed.path == "/test/notify":
            message = (body or {}).get("message") or (
                "🔔 Тест: новий лід у воронці KeyCRM\nПотрібно звʼязатись!\n\n📋 Тестове сповіщення"
            )
            return self._send(200, {"ok": True, "telegram": notify_telegram(message)})
        return self._send(404, {"ok": False, "error": "not_found"})

    def _handle_webhook(self, body: Any) -> None:
        log.info("webhook_raw %s", json.dumps(body, ensure_ascii=False)[:2000])
        try:
            if not isinstance(body, dict):
                return self._send(200, {"ok": False, "error": "invalid_body"})

            event = body.get("event")
            context = body.get("context", body)
            if isinstance(context, str):
                context = json.loads(context)

            if event and event != "lead.change_lead_status":
                return self._send(200, {"ok": True, "ignored": True, "reason": "not_lead_event"})

            if not is_new_lead_event(context):
                return self._send(200, {"ok": True, "skipped": True, "reason": "not_new_lead"})

            lead = enrich_lead(context)
            message = build_message(lead)
            log.info("new_lead %s", json.dumps(lead, ensure_ascii=False))
            tg = notify_telegram(message)
            return self._send(
                200,
                {
                    "ok": True,
                    "notified": True,
                    "lead_id": lead.get("id"),
                    "telegram": tg,
                    "keycrm_app_push": (
                        "Push у додаток KeyCRM — через тригер «Створити задачу» (див. GET /setup)"
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("webhook_error")
            # Always 200 so KeyCRM stops retrying on our logic bugs
            return self._send(200, {"ok": False, "error": str(exc)})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("keycrm-lead-push listening on http://127.0.0.1:%s", PORT)
    log.info("Setup guide: GET http://127.0.0.1:%s/setup", PORT)
    log.info("Webhook URL: POST http://127.0.0.1:%s/webhook/keycrm", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutdown")
        server.shutdown()


if __name__ == "__main__":
    main()
