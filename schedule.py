#!/usr/bin/env python3
"""Scheduling policy for the ticket monitor.

The workflow has no cron of its own — GitHub delivers scheduled events on a
best-effort basis, far too unevenly to hold to a fixed number of runs a day.
The Cloudflare Worker in cloudflare/ dispatches it instead, and this module
decides again, on arrival, whether the run should go ahead: one attempt per
Pacific hour in RUN_HOURS, which caps the workflow at eight runs a day however
it was triggered.

Deliberately free of third-party imports, so the workflow can evaluate the
guard immediately after checkout and turn a run away before installing
anything.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
# The Pacific hours we want one observation in, and the single source of truth
# for the schedule. The Worker's cron only has to tick often enough to land
# inside each of them.
RUN_HOURS = (1, 6, 7, 8, 9, 10, 11, 12)
CHECKS_PER_DAY = len(RUN_HOURS)
HISTORY_DAYS = 2
# One heartbeat at the final check of each contiguous block of RUN_HOURS.
SUMMARY_HOURS = (1, 12)
# One attempt per run hour, which pins the workflow to at most eight runs a
# day. An hour is spent as soon as an attempt is logged for it, successful or
# not: a failed check is recorded in state/run-status.json and shown on the
# dashboard rather than retried.
MAX_ATTEMPTS_PER_HOUR = 1


def now_pacific(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC)


def hour_key(moment: datetime | str) -> str:
    """Identify the Pacific hour an instant falls in, e.g. '2026-09-13T10'."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return now_pacific(moment).strftime("%Y-%m-%dT%H")


def scheduled_now(now: datetime | None = None) -> bool:
    return now_pacific(now).hour in RUN_HOURS


def block_summary_due(now: datetime | None = None) -> bool:
    return now_pacific(now).hour in SUMMARY_HOURS


def recorded_hours(state: dict | None) -> set[str]:
    """Every Pacific hour already covered by a recorded observation.

    Deliveries arrive out of order — a slot delayed an hour can land after a
    punctual later one — so this looks across the retained history rather than
    at the newest entry alone, which would let the overtaken hour run twice.
    """
    if not state:
        return set()
    history = state.get("history") or [state]
    return {
        hour_key(item["checked_at"]) for item in history
        if isinstance(item, dict) and item.get("checked_at")
    }


def attempts_in_hour(runs: dict | None, key: str) -> int:
    """How many workflow attempts have already been logged for a Pacific hour."""
    if not runs:
        return 0
    return sum(
        1 for item in runs.get("history") or []
        if isinstance(item, dict) and item.get("recorded_at")
        and hour_key(item["recorded_at"]) == key
    )


def due(state: dict | None, now: datetime | None = None,
        runs: dict | None = None) -> tuple[bool, str]:
    """Decide whether this arrival should perform a check, and say why."""
    local = now_pacific(now)
    if local.hour not in RUN_HOURS:
        return False, f"{local:%H:%M} Pacific is outside the requested run hours"
    key = hour_key(local)
    if key in recorded_hours(state):
        return False, f"the {local:%H:00} Pacific check is already recorded"
    # Only reached when the hour has no observation, so any logged attempt for
    # it failed. The hour is spent either way.
    attempts = attempts_in_hour(runs, key)
    if attempts >= MAX_ATTEMPTS_PER_HOUR:
        return False, f"the {local:%H:00} Pacific hour already used its attempt"
    return True, f"no check recorded yet for {local:%H:00} Pacific"


def load_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        # A missing or half-written state file must not stop a check.
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("state/current.json"))
    parser.add_argument("--runs", type=Path, default=Path("state/run-status.json"))
    parser.add_argument("--force", action="store_true", help="bypass the guard (manual runs)")
    args = parser.parse_args()

    if args.force:
        should_run, reason = True, "manually dispatched"
    else:
        should_run, reason = due(load_state(args.state), runs=load_state(args.runs))
    print(f"due={'true' if should_run else 'false'}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
