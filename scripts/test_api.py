#!/usr/bin/env python3
"""Check KeyCRM API connectivity. Use --create-lead to create a test card."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from server import keycrm_fetch, load_dotenv  # noqa: E402


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-lead", action="store_true")
    args = parser.parse_args()

    pipelines = keycrm_fetch("/pipelines")
    print("Pipelines:")
    for p in pipelines.get("data") or []:
        print(f"  #{p['id']} {p['title']}")

    users = keycrm_fetch("/users?limit=50")
    print("\nUsers:")
    for u in users.get("data") or []:
        print(f"  #{u['id']} {u.get('full_name')} <{u.get('email')}> role={u.get('role_id')}")

    statuses = keycrm_fetch("/pipelines/1/statuses")
    print("\nStatuses pipeline #1:")
    for s in statuses.get("data") or []:
        print(f"  #{s['id']} {s['title']} alias={s.get('alias')} final={s.get('is_final')}")

    if args.create_lead:
        card = keycrm_fetch(
            "/pipelines/cards",
            method="POST",
            body={
                "title": "TEST PUSH — новий лід, звʼязатись",
                "pipeline_id": 1,
                "manager_comment": "Тестовий лід з scripts/test_api.py. Можна видалити.",
                "contact": {"full_name": "Тест Інтеграція", "phone": "+380991112233"},
            },
        )
        print("\nCreated test lead:")
        print(json.dumps(card, ensure_ascii=False, indent=2))

    print("\nOK")


if __name__ == "__main__":
    main()
