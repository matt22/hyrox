#!/usr/bin/env python3
"""Scheduling policy for the ticket monitor.

The workflow has no cron of its own — GitHub delivers scheduled events on a
best-effort basis, far too unevenly to hold to a fixed number of runs a day.
The Cloudflare Worker in cloudflare/ dispatches it instead, and this module
decides again, on arrival, whether the run should go ahead: one attempt per
Pacific hour in RUN_HOURS, which caps the workflow at eight runs a day however
it was triggered. Every active event in config/events.json is guarded
separately, in its own timezone and run hours, against its own state under
state/<event-key>/.

Deliberately free of third-party imports, so the workflow can evaluate the
guard immediately after checkout and turn a run away before installing
anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
# The Pacific hours we want one observation in, and the single source of truth
# for the schedule. The Worker's cron (cloudflare/wrangler.toml) lists these
# same eight hours directly, so a change here needs a matching change there —
# test_worker_cron_reaches_every_run_hour_in_both_offsets in
# tests/test_schedule.py fails if the two drift apart.
RUN_HOURS = (0, 1, 7, 8, 9, 10, 11, 12)
CHECKS_PER_DAY = len(RUN_HOURS)
HISTORY_DAYS = 2
# One heartbeat at the final check of each contiguous block of RUN_HOURS.
SUMMARY_HOURS = (1, 12)
# One attempt per run hour, which pins the workflow to at most eight runs a
# day. An hour is spent as soon as an attempt is logged for it, successful or
# not: a failed check is recorded in state/run-status.json and shown on the
# dashboard rather than retried.
MAX_ATTEMPTS_PER_HOUR = 1
# Checks stop this many days before the first day of competition (from
# midnight Pacific that day): openings that late are no use to us.
STOP_DAYS_BEFORE_COMPETITION = 5
EVENTS_CONFIG = Path(__file__).resolve().parent / "config/events.json"
# Each event keeps its own current.json, run-status.json and openings.json here.
STATE_ROOT = Path("state")


def now_in_zone(tz: ZoneInfo, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(tz)


def now_pacific(now: datetime | None = None) -> datetime:
    return now_in_zone(PACIFIC, now)


def hour_key(moment: datetime | str, tz: ZoneInfo = PACIFIC) -> str:
    """Identify the tz-local hour an instant falls in, e.g. '2026-09-13T10'.

    Every event currently monitored uses Pacific, hence the default; a
    non-Pacific event just needs to pass its own IANA zone here and to `due`.
    """
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return now_in_zone(tz, moment).strftime("%Y-%m-%dT%H")


def scheduled_now(now: datetime | None = None, *, tz: ZoneInfo = PACIFIC,
                   run_hours: tuple[int, ...] = RUN_HOURS) -> bool:
    return now_in_zone(tz, now).hour in run_hours


def block_summary_due(now: datetime | None = None, *, tz: ZoneInfo = PACIFIC,
                       summary_hours: tuple[int, ...] = SUMMARY_HOURS) -> bool:
    return now_in_zone(tz, now).hour in summary_hours


def recorded_hours(state: dict | None, tz: ZoneInfo = PACIFIC) -> set[str]:
    """Every tz-local hour already covered by a recorded observation.

    Deliveries arrive out of order — a slot delayed an hour can land after a
    punctual later one — so this looks across the retained history rather than
    at the newest entry alone, which would let the overtaken hour run twice.
    """
    if not state:
        return set()
    history = state.get("history") or [state]
    return {
        hour_key(item["checked_at"], tz) for item in history
        if isinstance(item, dict) and item.get("checked_at")
    }


def attempts_in_hour(runs: dict | None, key: str, tz: ZoneInfo = PACIFIC) -> int:
    """How many workflow attempts have already been logged for a tz-local hour."""
    if not runs:
        return 0
    return sum(
        1 for item in runs.get("history") or []
        if isinstance(item, dict) and item.get("recorded_at")
        and hour_key(item["recorded_at"], tz) == key
    )


def load_events(config: Path = EVENTS_CONFIG) -> dict:
    return load_state(config) or {}


def default_event_key(config: Path = EVENTS_CONFIG) -> str | None:
    return next((key for key, item in load_events(config).items() if item.get("is_default")), None)


def active_events(config: Path = EVENTS_CONFIG) -> dict:
    """Events the monitor checks: marked active and with a ticket shop to scrape."""
    return {
        key: item for key, item in load_events(config).items()
        if item.get("status") == "active" and item.get("source_url")
    }


def state_dir(key: str, root: Path = STATE_ROOT) -> Path:
    return root / key


def event_zone(event: dict) -> ZoneInfo:
    return ZoneInfo(event.get("timezone") or PACIFIC.key)


def event_run_hours(event: dict) -> tuple[int, ...]:
    return tuple(event.get("run_hours") or RUN_HOURS)


def checks_stop_on(config: Path = EVENTS_CONFIG, key: str | None = None) -> date | None:
    """The tz-local date checks stop for an event (the default one if no key), if it has one."""
    events = load_events(config)
    event = events.get(key or default_event_key(config) or "", {})
    first_day = event.get("first_competition_date")
    if not first_day:
        return None
    return date.fromisoformat(first_day) - timedelta(days=STOP_DAYS_BEFORE_COMPETITION)


def due(state: dict | None, now: datetime | None = None, runs: dict | None = None, *,
        tz: ZoneInfo = PACIFIC, run_hours: tuple[int, ...] = RUN_HOURS,
        stop_on: date | None = None) -> tuple[bool, str]:
    """Decide whether this arrival should perform a check, and say why.

    `tz` and `run_hours` default to the Anaheim schedule so every existing
    caller (the CLI below, monitor.py) is unaffected; a future per-event
    caller passes that event's own `timezone`/`run_hours` from
    config/events.json instead.
    """
    local = now_in_zone(tz, now)
    if stop_on and local.date() >= stop_on:
        return False, f"checks stopped on {stop_on}, {STOP_DAYS_BEFORE_COMPETITION} days before competition"
    if local.hour not in run_hours:
        return False, f"{local:%H:%M} {tz.key} is outside the requested run hours"
    key = hour_key(local, tz)
    if key in recorded_hours(state, tz):
        return False, f"the {local:%H:00} {tz.key} check is already recorded"
    # Only reached when the hour has no observation, so any logged attempt for
    # it failed. The hour is spent either way.
    attempts = attempts_in_hour(runs, key, tz)
    if attempts >= MAX_ATTEMPTS_PER_HOUR:
        return False, f"the {local:%H:00} {tz.key} hour already used its attempt"
    return True, f"no check recorded yet for {local:%H:00} {tz.key}"


def load_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        # A missing or half-written state file must not stop a check.
        return None


def event_due(key: str, event: dict, now: datetime | None = None, *,
              config: Path = EVENTS_CONFIG, root: Path = STATE_ROOT) -> tuple[bool, str]:
    """`due` for one registry event, against that event's own state and schedule."""
    directory = state_dir(key, root)
    return due(
        load_state(directory / "current.json"), now, load_state(directory / "run-status.json"),
        tz=event_zone(event), run_hours=event_run_hours(event),
        stop_on=checks_stop_on(config, key),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", help="guard only this event key (default: every active event)")
    parser.add_argument("--force", action="store_true", help="bypass the guard (manual runs)")
    args = parser.parse_args()

    events = active_events()
    if args.event:
        if args.event not in events:
            raise SystemExit(f"{args.event!r} is not an active event in {EVENTS_CONFIG.name}")
        events = {args.event: events[args.event]}

    due_keys = []
    for key, event in events.items():
        should_run, reason = (True, "manually dispatched") if args.force else event_due(key, event)
        if should_run:
            due_keys.append(key)
        # Reasons go to stderr so stdout stays clean key=value lines for $GITHUB_OUTPUT.
        print(f"{key}: {'due' if should_run else 'skip'} — {reason}", file=sys.stderr)
    print(f"due={'true' if due_keys else 'false'}")
    print(f"events={json.dumps(due_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
