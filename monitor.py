#!/usr/bin/env python3
"""Deterministic HYROX Anaheim ticket availability monitor."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


EVENT_URL = "https://usa.hyrox.com/events/hyrox-anaheim-season-26-27-edyxxn"
PACIFIC = ZoneInfo("America/Los_Angeles")
RUN_HOURS = {0, 1, 7, 8, 9, 10, 11, 12}
HISTORY_DAYS = 2

# Keep this list deliberately narrow. Matching happens after excluded ticket types
# are rejected, so Charity/Adaptive/Pro/Spectator variants never leak in.
TARGET_PATTERNS = {
    "Men's Open Singles": (r"\bmen(?:'s)?\b", r"^(?!.*\b(?:doubles?|relay)\b).*\b(?:open|singles?)\b"),
    "Women's Open Singles": (r"\bwomen(?:'s)?\b", r"^(?!.*\b(?:doubles?|relay)\b).*\b(?:open|singles?)\b"),
    "Women's Open Doubles": (r"\bwomen(?:'s)?\b", r"\bdoubles?\b"),
    "Mixed Open Doubles": (r"\bmixed\b", r"\bdoubles?\b"),
    "Mixed Open Relay": (r"\bmixed\b", r"\brelay\b"),
}
TARGET_WIZARD_PATHS = {
    "Men's Open Singles": ("Singles", "Open", "Men"),
    "Women's Open Singles": ("Singles", "Open", "Women"),
    "Women's Open Doubles": ("Doubles", "Open", "Women"),
    "Mixed Open Doubles": ("Doubles", "Open", "Mixed"),
    "Mixed Open Relay": ("Relay", "Open", "Mixed"),
}
EXCLUDED = re.compile(r"\b(charity|adaptive|pro|spectator|youngstars?)\b", re.I)
AVAILABLE = re.compile(r"\b(buy|select|register|available|from\s+\$|add)\b", re.I)
UNAVAILABLE = re.compile(r"\b(sold\s*out|unavailable|waitlist|closed|coming\s*soon)\b", re.I)


class StructureError(RuntimeError):
    """The page loaded, but did not expose all expected ticket categories."""


@dataclass(frozen=True)
class Ticket:
    status: str
    evidence: str


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def classify(text: str) -> str:
    if UNAVAILABLE.search(text):
        return "unavailable"
    if AVAILABLE.search(text):
        return "available"
    return "unknown"


def parse_ticket_texts(blocks: Iterable[str]) -> dict[str, Ticket]:
    matches: dict[str, list[str]] = {name: [] for name in TARGET_PATTERNS}
    for raw in blocks:
        text = normalize(raw)
        if not text or EXCLUDED.search(text):
            continue
        for name, patterns in TARGET_PATTERNS.items():
            if all(re.search(pattern, text, re.I) for pattern in patterns):
                matches[name].append(text)

    missing = sorted(name for name, evidence in matches.items() if not evidence)
    if missing:
        raise StructureError("Expected ticket categories were not found: " + ", ".join(missing))
    results = {}
    for name, evidence in matches.items():
        statuses = [classify(text) for text in evidence]
        # A category is available when any date/wave can be bought.
        status = "available" if "available" in statuses else (
            "unavailable" if "unavailable" in statuses else "unknown"
        )
        results[name] = Ticket(status, " | ".join(evidence)[:500])
    unknown = [name for name, ticket in results.items() if ticket.status == "unknown"]
    if unknown:
        raise StructureError("Availability wording was not recognized for: " + ", ".join(unknown))
    return results


def candidate_blocks(page: Page) -> list[str]:
    selectors = (
        "article", "li", "tr", "[class*='ticket']", "[class*='product']",
        "[class*='card']", "[role='listitem']", "form",
    )
    blocks: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 500)):
            try:
                text = normalize(locator.nth(index).inner_text(timeout=1_000))
            except Exception:
                continue
            if 3 <= len(text) <= 2_000:
                blocks.append(text)
    # A fallback for simpler shops where every option is merely a button/link.
    for selector in ("button", "a"):
        locator = page.locator(selector)
        for index in range(min(locator.count(), 500)):
            try:
                text = normalize(locator.nth(index).inner_text(timeout=500))
            except Exception:
                continue
            if text:
                blocks.append(text)
    return list(dict.fromkeys(blocks))


def wizard_blocks(page: Page) -> list[str]:
    """Traverse only the five explicitly requested Vivenu wizard branches."""
    ticket_url = page.url
    blocks = []
    for name, path in TARGET_WIZARD_PATHS.items():
        page.goto(ticket_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)
        for step in path:
            button = page.get_by_role("button", name=step, exact=True)
            if not button.count():
                # Some event configurations omit the redundant Open stage.
                if step == "Open":
                    continue
                raise StructureError(f"Vivenu wizard path for {name} has no {step!r} option")
            button.first.click(timeout=8_000)
            page.wait_for_timeout(750)
        text = normalize(page.locator("body").inner_text(timeout=5_000))
        if not text:
            raise StructureError(f"Vivenu wizard returned an empty result for {name}")
        # Vivenu may show excluded alternatives beside the selected Open branch.
        # Keep only leaf-ish blocks with recognizable status wording, and reject
        # exclusions per ticket card rather than rejecting the whole results page.
        status_blocks = [
            block for block in candidate_blocks(page)
            if not EXCLUDED.search(block) and classify(block) != "unknown"
        ]
        if not status_blocks and not EXCLUDED.search(text) and classify(text) != "unknown":
            status_blocks = [text]
        if not status_blocks:
            raise StructureError(f"Vivenu returned no recognizable Open ticket status for {name}")
        blocks.extend(f"{name} {block}" for block in status_blocks)
    return blocks


def open_ticket_shop(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_000)
    # Cookie overlays can cover the ticket link but do not affect deterministic parsing.
    for label in ("Accept All", "Accept all", "Allow all", "I agree"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count():
            try:
                button.first.click(timeout=2_000)
            except Exception:
                pass
            break

    if "usa.hyrox.com" in page.url:
        button = page.get_by_role("button", name="Buy Tickets", exact=True)
        if not button.count():
            raise StructureError("The canonical ticket shop did not expose its Buy Tickets button")
        button.first.click(timeout=8_000)
        page.wait_for_timeout(3_000)
        return

    ticket_links = page.locator("a", has_text=re.compile(r"buy|ticket|register", re.I))
    for index in range(min(ticket_links.count(), 20)):
        link = ticket_links.nth(index)
        text = normalize(link.inner_text())
        href = link.get_attribute("href") or ""
        if re.search(r"buy|ticket|register", text + " " + href, re.I):
            try:
                if href and not href.lower().startswith(("javascript:", "#")):
                    page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=30_000)
                else:
                    link.click(timeout=8_000)
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
                page.wait_for_timeout(3_000)
                return
            except PlaywrightTimeoutError:
                # Some vendors keep a long-lived connection; parsing can still proceed.
                return


def capture(page: Page, directory: Path, error: Exception) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page.html").write_text(page.content(), encoding="utf-8")
    (directory / "visible-text.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
    (directory / "error.txt").write_text(f"{type(error).__name__}: {error}\nURL: {page.url}\n", encoding="utf-8")
    page.screenshot(path=str(directory / "page.png"), full_page=True)


def check(url: str, diagnostics: Path, headless: bool = True) -> dict[str, Ticket]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="en-US", timezone_id="America/Los_Angeles",
            viewport={"width": 1440, "height": 1200},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/138 Safari/537.36",
        )
        page = context.new_page()
        try:
            open_ticket_shop(page, url)
            blocks = wizard_blocks(page) if "usa.hyrox.com/tickets/" in page.url else candidate_blocks(page)
            return parse_ticket_texts(blocks)
        except Exception as error:
            capture(page, diagnostics, error)
            raise
        finally:
            browser.close()


def state_payload(tickets: dict[str, Ticket], url: str) -> dict:
    return {
        "event": "Centr HYROX Anaheim 2026",
        "source_url": url,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tickets": {name: asdict(ticket) for name, ticket in tickets.items()},
    }


def changes(previous: dict | None, current: dict) -> list[str]:
    if not previous:
        return []
    old = latest_observation(previous).get("tickets", {})
    lines = []
    for name, ticket in current["tickets"].items():
        before = old.get(name, {}).get("status", "unknown")
        after = ticket["status"]
        if before != after:
            lines.append(f"{name}: {before} -> {after}")
    return lines


def latest_observation(state: dict) -> dict:
    """Return the newest observation from either the rolling or legacy schema."""
    history = state.get("history", [])
    return history[-1] if history else state


def requested_history_limit() -> int:
    """Derive retention from the requested daily Pacific run hours."""
    return len(RUN_HOURS) * HISTORY_DAYS


def rolling_state(previous: dict | None, current: dict, limit: int | None = None) -> dict:
    """Append a successful observation and retain the requested history size."""
    limit = requested_history_limit() if limit is None else limit
    if limit < 1:
        raise ValueError("Rolling history limit must be positive")
    history = list(previous.get("history", [])) if previous else []
    if previous and not history and previous.get("checked_at"):
        # One-time migration from the original latest-observation-only schema.
        history.append(previous)

    prior = latest_observation(previous) if previous else None
    prior_tickets = prior.get("tickets", {}) if prior else {}
    opened = [
        name for name, ticket in current["tickets"].items()
        if prior is not None
        and ticket["status"] == "available"
        and prior_tickets.get(name, {}).get("status") != "available"
    ]
    observation = {**current, "opened": opened}
    history.append(observation)
    history = history[-limit:]
    openings = {
        name: {
            "available_observations": sum(
                item.get("tickets", {}).get(name, {}).get("status") == "available"
                for item in history
            ),
            "opening_transitions": sum(name in item.get("opened", []) for item in history),
        }
        for name in TARGET_PATTERNS
    }
    return {
        "meta": {
            "total_openings": sum(len(item.get("opened", [])) for item in history),
            "retention_days": HISTORY_DAYS,
            "max_observations": limit,
            "observation_count": len(history),
            "window_start": history[0]["checked_at"],
            "window_end": history[-1]["checked_at"],
            "openings": openings,
        },
        "history": history,
    }


def scheduled_now(now: datetime | None = None) -> bool:
    local = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    return local.hour in RUN_HOURS


def block_summary_due(now: datetime | None = None) -> bool:
    """Send one heartbeat at the final check in each requested time block."""
    local = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    return local.hour in {1, 12}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("HYROX_TICKET_URL", EVENT_URL))
    parser.add_argument("--state", type=Path, default=Path("state/current.json"))
    parser.add_argument("--snapshot", type=Path, default=Path("state/latest.json"))
    parser.add_argument("--diagnostics", type=Path, default=Path("diagnostics"))
    parser.add_argument("--schedule-guard", action="store_true")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    if args.schedule_guard and not scheduled_now():
        print("Outside configured Pacific run hours; exiting without checking.")
        return 0

    try:
        tickets = check(args.url, args.diagnostics, not args.headed)
    except Exception as error:
        print(f"Monitor failed: {error}", file=sys.stderr)
        return 2

    previous = json.loads(args.state.read_text()) if args.state.exists() else None
    current = state_payload(tickets, args.url)
    delta = changes(previous, current)
    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rolling = rolling_state(previous, current)
    # Preserve the intentionally human-oriented schema order: metadata first,
    # followed by chronological observations.
    args.state.write_text(json.dumps(rolling, indent=2) + "\n", encoding="utf-8")
    Path(os.getenv("GITHUB_OUTPUT", os.devnull)).open("a", encoding="utf-8").write(
        f"initialized={'true' if previous else 'false'}\n"
        f"changed={'true' if delta else 'false'}\n"
        f"block_summary_due={'true' if block_summary_due() else 'false'}\n"
        f"changes={json.dumps(delta)}\n"
    )
    print("\n".join(delta) if delta else "No availability changes detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
