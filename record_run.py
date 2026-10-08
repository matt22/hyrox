#!/usr/bin/env python3
"""Log one workflow attempt to an event's state/<event-key>/run-status.json.

Deliberately stdlib-only and independent of schedule.py: it must still log
when the guard failed because schedule.py itself is broken.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Only due slots are recorded, so this tracks the dashboard window plus a spare
# day of failure markers. Deliberately not imported from schedule.py (see
# above); a test keeps the two in step.
LIMIT = 24  # CHECKS_PER_DAY * (HISTORY_DAYS + 1)
EVENTS_CONFIG = Path("config/events.json")


def record(path: Path, attempt: dict) -> dict:
    previous = json.loads(path.read_text()) if path.exists() else None
    if previous and "history" in previous:
        history = previous["history"]
    elif previous and previous.get("run_id"):
        history = [previous]
    else:
        history = []
    history = [
        item for item in history
        if (item.get("run_id"), item.get("run_attempt"))
        != (attempt["run_id"], attempt["run_attempt"])
    ]
    history.append(attempt)
    history = history[-LIMIT:]
    return {"meta": {"max_attempts": LIMIT, "attempt_count": len(history)}, "history": history}


def active_event_keys() -> list[str]:
    events = json.loads(EVENTS_CONFIG.read_text())
    return [
        key for key, item in events.items()
        if item.get("status") == "active" and item.get("source_url")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--event", help="registry key")
    target.add_argument("--all-active", action="store_true", help="every active event")
    parser.add_argument("--outcome", default=os.environ.get("MONITOR_OUTCOME") or "skipped")
    args = parser.parse_args()

    attempt = {
        "status": "success" if args.outcome == "success" else "failure",
        "monitor_outcome": args.outcome,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": int(os.environ["RUN_ID"]),
        "run_attempt": int(os.environ["RUN_ATTEMPT"]),
        "run_url": os.environ["RUN_URL"],
    }
    for key in active_event_keys() if args.all_active else [args.event]:
        path = Path("state") / key / "run-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record(path, attempt), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
