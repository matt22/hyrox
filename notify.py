#!/usr/bin/env python3
"""Render a GitHub-flavored Markdown ticket notification."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def notification_users(raw: str) -> list[str]:
    users = []
    for value in raw.split(","):
        user = value.strip().removeprefix("@")
        if user and USERNAME.fullmatch(user) and user not in users:
            users.append(user)
    if not users:
        raise ValueError("At least one valid GitHub notification username is required")
    return users


def render_markdown(state: dict, changes: list[str], users: list[str]) -> str:
    mentions = " ".join(f"@{user}" for user in users)
    if changes:
        heading = "## Availability changed"
        callout = "> [!IMPORTANT]\n> " + "<br>\n> ".join(changes)
    else:
        heading = "## Scheduled status summary"
        callout = "> [!NOTE]\n> The monitor completed the current Pacific-time check block."

    rows = "\n".join(
        f"| {name.replace('|', chr(92) + '|')} | "
        f"{'✅ **AVAILABLE**' if item['status'] == 'available' else 'Not available'} |"
        for name, item in state["tickets"].items()
    )
    return f"""{mentions}

{heading}

{callout}

| Tracked ticket | Status |
|---|---:|
{rows}

[Open the official HYROX Anaheim event page]({state['source_url']})

<sub>Checked {state['checked_at']} · Deterministic Python/Playwright monitor</sub>
"""


def main() -> None:
    state_path = Path(os.getenv("HYROX_STATE_PATH", "state/latest.json"))
    output_path = Path(os.getenv("HYROX_NOTIFICATION_PATH", "notification.md"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    changes = json.loads(os.getenv("HYROX_CHANGES", "[]"))
    default_user = os.getenv("GITHUB_REPOSITORY_OWNER", "matt22")
    raw_users = os.getenv("HYROX_NOTIFY_USERS", "").strip() or default_user
    users = notification_users(raw_users)
    output_path.write_text(render_markdown(state, changes, users), encoding="utf-8")


if __name__ == "__main__":
    main()
