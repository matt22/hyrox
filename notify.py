#!/usr/bin/env python3
"""Render one GitHub-flavored Markdown notification covering every active event.

The workflow's notify job runs this once per dispatched run, after every
event's check job. Each check job leaves results/<event-key>.json (outcome and
availability changes) next to its state/<event-key>/ files; this combines them
with the rest of the registry into a single comment on one persistent issue,
so a run is one email however many events it checked.

Stdlib-only, like schedule.py, so the notify job needs no install.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from schedule import (
    EVENTS_CONFIG, STATE_ROOT, checks_stop_on, load_events, load_state, now_in_zone, event_zone,
    state_dir,
)


USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
# One persistent issue for every event, so GitHub's email subject stays fixed.
ISSUE_TITLE = "🟢 HYROX ticket monitor"
DASHBOARD_URL = "https://matt22.github.io/hyrox/"
RESULTS_DIR = Path("results")


def notification_users(raw: str) -> list[str]:
    users = []
    for value in raw.split(","):
        user = value.strip().removeprefix("@")
        if user and USERNAME.fullmatch(user) and user not in users:
            users.append(user)
    if not users:
        raise ValueError("At least one valid GitHub notification username is required")
    return users


def cell(value: str) -> str:
    return value.replace("|", "\\|")


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def date_range(event: dict) -> str:
    """'Feb 25–28', 'Feb 27–Mar 2', or just the first day when that's all we know."""
    raw = event.get("event_dates") or ""
    if " to " in raw:
        first, last = (date.fromisoformat(part.strip()) for part in raw.split(" to ", 1))
        return f"{short_date(first)}–{last.day if last.month == first.month else short_date(last)}"
    first = event.get("first_competition_date")
    return short_date(date.fromisoformat(first)) if first else "—"


def dashboard_url(key: str, event: dict) -> str:
    return DASHBOARD_URL if event.get("is_default") else f"{DASHBOARD_URL}?event={key}"


def latest_observation(state: dict | None) -> dict | None:
    if not state:
        return None
    history = state.get("history") or []
    return history[-1] if history else (state if state.get("tickets") else None)


def event_row(key: str, event: dict, observation: dict | None, result: dict | None,
              today: date, stop_on: date | None) -> dict:
    """Everything the notification shows for one event."""
    divisions = event.get("divisions_tracked") or []
    tickets = (observation or {}).get("tickets", {})
    open_names = [name for name in divisions if tickets.get(name, {}).get("status") == "available"]
    row = {
        "key": key,
        "label": f"{event.get('city', key)} {event.get('year', '')}".strip(),
        "city": event.get("city", key),
        "url": dashboard_url(key, event),
        "dates": date_range(event),
        "sort": event.get("first_competition_date") or "9999",
        "open": open_names,
        "total": len(divisions),
        "changes": (result or {}).get("changes") or [],
        "failed": bool(result) and result.get("outcome") != "success",
    }
    if not event.get("source_url"):
        sale = event.get("first_ticket_sale_date")
        approx = "" if event.get("first_ticket_sale_date_confirmed") else "~"
        row["open_cell"] = "—"
        row["status"] = f"Pre-sale · sale {approx}{short_date(date.fromisoformat(sale))}" if sale else "Pre-sale"
        return row
    row["open_cell"] = f"✅ {len(open_names)} / {len(divisions)}" if open_names else (
        f"0 / {len(divisions)}" if observation else "—"
    )
    if row["failed"]:
        row["status"] = "⚠️ Check failed"
    elif not observation:
        row["status"] = "Not checked yet"
    elif stop_on and today >= stop_on:
        row["status"] = "Checks stopped"
    else:
        row["status"] = ", ".join(open_names) if open_names else "None open"
    return row


def render_markdown(rows: list[dict], users: list[str], *, run_url: str | None = None) -> str:
    mentions = " ".join(f"@{user}" for user in users)
    rows = sorted(rows, key=lambda row: (not row["open"], row["sort"], row["label"]))
    changed = [row for row in rows if row["changes"]]
    openings = [row for row in changed if any(c.endswith("-> available") for c in row["changes"])]
    lines = [
        f"**{row['city']}**: {change}"
        # Openings first, then any other changes.
        for row in openings + [row for row in changed if row not in openings]
        for change in sorted(row["changes"], key=lambda c: not c.endswith("-> available"))
    ]
    if openings:
        heading = "## 🟢 TICKETS AVAILABLE — " + ", ".join(row["city"] for row in openings)
        callout = (
            "> [!IMPORTANT]\n"
            "> 🟢 **Tickets are available now — act quickly.**<br>\n> " + "<br>\n> ".join(lines)
        )
    elif changed:
        heading = "## Availability changed — " + ", ".join(row["city"] for row in changed)
        callout = "> [!IMPORTANT]\n> " + "<br>\n> ".join(lines)
    else:
        heading = "## Daily status summary"
        callout = "> [!NOTE]\n> No availability changes in this check."

    def status(row: dict) -> str:
        if row["failed"] and run_url:
            return f"[{row['status']}]({run_url})"
        return cell(row["status"])

    table = "\n".join(
        f"| [{cell(row['label'])}]({row['url']}) | {row['dates']} | {row['open_cell']} | {status(row)} |"
        for row in rows
    )
    footer = f"[Workflow run]({run_url}) · " if run_url else ""
    return f"""{mentions}

{heading}

{callout}

| Event | Dates | Open | Status |
|---|---|---:|---|
{table}

<sub>{footer}Deterministic Python/Playwright monitor</sub>
"""


def collect_rows(config: Path = EVENTS_CONFIG, root: Path = STATE_ROOT,
                 results_dir: Path = RESULTS_DIR) -> list[dict]:
    """A row per active event, including pre-sale ones that have no shop yet."""
    rows = []
    for key, event in load_events(config).items():
        if event.get("status") != "active":
            continue
        observation = latest_observation(load_state(state_dir(key, root) / "current.json"))
        result = load_state(results_dir / f"{key}.json")
        today = now_in_zone(event_zone(event)).date()
        rows.append(event_row(key, event, observation, result, today, checks_stop_on(config, key)))
    return rows


def should_notify(rows: list[dict], summary_due: bool) -> bool:
    return summary_due or any(row["changes"] for row in rows)


def main() -> None:
    output_path = Path(os.getenv("HYROX_NOTIFICATION_PATH", "notification.md"))
    rows = collect_rows(results_dir=Path(os.getenv("HYROX_RESULTS_DIR", RESULTS_DIR)))
    notify = should_notify(rows, os.getenv("HYROX_SUMMARY_DUE") == "true")
    default_user = os.getenv("GITHUB_REPOSITORY_OWNER", "matt22")
    raw_users = os.getenv("HYROX_NOTIFY_USERS", "").strip() or default_user
    if notify:
        output_path.write_text(
            render_markdown(rows, notification_users(raw_users), run_url=os.getenv("RUN_URL")),
            encoding="utf-8",
        )
    Path(os.getenv("GITHUB_OUTPUT", os.devnull)).open("a", encoding="utf-8").write(
        f"notify={'true' if notify else 'false'}\nissue_title={ISSUE_TITLE}\n"
    )
    print(f"Notification {'rendered' if notify else 'not due'} for {len(rows)} active events.")


if __name__ == "__main__":
    main()
