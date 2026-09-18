"""The scheduling policy, and the cron expression that has to feed it."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from schedule import (
    CHECKS_PER_DAY, HISTORY_DAYS, MAX_ATTEMPTS_PER_HOUR, PACIFIC, RUN_HOURS, due,
    hour_key, scheduled_now,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/monitor.yml"
WRANGLER = ROOT / "cloudflare/wrangler.toml"
# The hourly cron is deliberately built to land exactly once per Pacific run
# hour, not with spare ticks to fall back on: Cloudflare does not retry a tick
# it drops, so a dropped tick now costs that hour's check for the day.
REQUIRED_TICKS_PER_HOUR = 1


def at(pacific_iso: str) -> datetime:
    return datetime.fromisoformat(pacific_iso).replace(tzinfo=PACIFIC)


def state_checked_at(*utc_iso: str) -> dict:
    return {"history": [{"checked_at": moment} for moment in utc_iso]}


def cron_field(field: str, span: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part, _, step = part.partition("/")
        step = int(step) if step else 1
        if part == "*":
            low, high = 0, span - 1
        elif "-" in part:
            low, high = (int(bound) for bound in part.split("-"))
        else:
            low = high = int(part)
            if step > 1:  # `n/step` means n, n+step, ... in cron
                high = span - 1
        values |= set(range(low, high + 1, step))
    return values


def cron_arrivals() -> list[tuple[int, int]]:
    """Every (UTC hour, minute) the Cloudflare Worker wakes up on."""
    crons = re.findall(r'"([^"]+)"', re.search(r"crons\s*=\s*\[([^\]]*)\]", WRANGLER.read_text()).group(1))
    assert crons, "the Worker no longer declares a cron trigger"
    slots: set[tuple[int, int]] = set()
    for expression in crons:
        minute, hour = expression.split()[:2]
        slots |= {(h, m) for h in cron_field(hour, 24) for m in cron_field(minute, 60)}
    return sorted(slots)


@pytest.mark.parametrize("day", ["2026-07-15", "2026-01-15"], ids=["PDT", "PST"])
def test_worker_cron_reaches_every_run_hour_in_both_offsets(day):
    """The old fixed-UTC window silently lost a run hour every summer. This is that guard."""
    arrivals = {hour: 0 for hour in RUN_HOURS}
    for utc_hour, minute in cron_arrivals():
        moment = datetime.fromisoformat(f"{day}T{utc_hour:02d}:{minute:02d}:00+00:00")
        local = moment.astimezone(PACIFIC).hour
        if local in arrivals:
            arrivals[local] += 1

    unreachable = sorted(hour for hour, count in arrivals.items() if not count)
    assert not unreachable, f"the Worker never ticks during Pacific hour(s) {unreachable}"
    thin = {hour: count for hour, count in arrivals.items() if count < REQUIRED_TICKS_PER_HOUR}
    assert not thin, f"a single dropped tick would lose Pacific hour(s): {thin}"
    extra = {hour: count for hour, count in arrivals.items() if count > REQUIRED_TICKS_PER_HOUR}
    assert not extra, f"expected exactly one tick per Pacific run hour, got: {extra}"


def test_run_hours_are_the_only_schedule():
    assert scheduled_now(at("2026-09-13T10:30")) is True
    assert scheduled_now(at("2026-09-13T13:30")) is False


def test_first_arrival_in_a_run_hour_is_due():
    assert due(None, at("2026-09-13T10:03"))[0] is True


def test_later_arrivals_in_the_same_hour_are_skipped():
    state = state_checked_at("2026-09-13T17:05:00+00:00")  # 10:05 Pacific
    assert due(state, at("2026-09-13T10:23"))[0] is False
    assert due(state, at("2026-09-13T10:43"))[0] is False


def test_the_next_run_hour_is_due_again():
    state = state_checked_at("2026-09-13T17:05:00+00:00")  # 10:05 Pacific
    assert due(state, at("2026-09-13T11:03"))[0] is True


def test_a_failed_hour_is_retried_by_the_next_arrival():
    """Nothing is recorded when a check fails, so the hour stays due."""
    state = state_checked_at("2026-09-13T16:05:00+00:00")  # 9:05 Pacific
    assert due(state, at("2026-09-13T10:23"))[0] is True


def test_arrivals_outside_run_hours_are_skipped_whatever_the_state():
    assert due(None, at("2026-09-13T13:03"))[0] is False


def test_the_repeated_dst_fallback_hour_is_checked_once():
    """1 AM happens twice when clocks go back; one check for it is enough."""
    before = datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)  # 1:30 PDT
    after = before + timedelta(hours=1)  # 1:30 PST, the same wall clock
    assert hour_key(before) == hour_key(after) == "2026-11-01T01"
    assert due(state_checked_at(before.isoformat()), after)[0] is False


def test_missing_state_file_does_not_block_a_check(tmp_path):
    from schedule import load_state

    assert load_state(tmp_path / "absent.json") is None
    corrupt = tmp_path / "current.json"
    corrupt.write_text("{not json")
    assert load_state(corrupt) is None


def test_an_hour_overtaken_by_a_delayed_arrival_is_not_checked_twice():
    """A slot delivered an hour late can be recorded before a punctual one."""
    state = state_checked_at(
        "2026-09-13T15:05:00+00:00",  # 8:05 Pacific
        "2026-09-13T17:18:00+00:00",  # 10:18 Pacific, delivered out of order
    )
    assert due(state, at("2026-09-13T10:43"))[0] is False
    assert due(state, at("2026-09-13T09:03"))[0] is True


def test_the_legacy_single_observation_schema_still_guards():
    assert due({"checked_at": "2026-09-13T17:05:00+00:00"}, at("2026-09-13T10:23"))[0] is False


def test_a_failed_hour_is_not_retried():
    """Eight attempts a day is the ceiling; a spent hour stays spent."""
    attempted = {"history": [{"recorded_at": "2026-09-13T17:05:00+00:00"}]}  # 10:05 Pacific
    blocked, reason = due(None, at("2026-09-13T10:23"), runs=attempted)
    assert blocked is False and "already used its attempt" in reason
    # The ceiling is per hour, so the next hour starts clean.
    assert due(None, at("2026-09-13T11:03"), runs=attempted)[0] is True


def test_attempts_in_other_hours_do_not_block_this_one():
    failures = {"history": [
        {"recorded_at": f"2026-09-13T1{hour}:0{n}:00+00:00"} for hour in (5, 6) for n in (1, 2)
    ]}
    assert due(None, at("2026-09-13T10:23"), runs=failures)[0] is True


def test_due_accepts_a_non_pacific_zone_independently_of_the_pacific_default():
    """A future Mountain-time event must not need its own copy of schedule.py."""
    from zoneinfo import ZoneInfo

    denver = ZoneInfo("America/Denver")
    # 10:03 Mountain is 9:03 Pacific — inside Anaheim's RUN_HOURS but not
    # Denver's, proving the two schedules are evaluated independently.
    denver_moment = datetime(2026, 9, 13, 16, 3, tzinfo=timezone.utc)  # 10:03 MDT / 9:03 PDT
    assert due(None, denver_moment, tz=denver, run_hours=(10,))[0] is True
    assert due(None, denver_moment, run_hours=(10,))[0] is False  # default tz=Pacific
    assert due(None, denver_moment, tz=denver, run_hours=(9,))[0] is False


def test_workflow_run_status_cap_matches_the_schedule_constants():
    """The workflow hardcodes this so it still logs when schedule.py is broken."""
    literal = re.search(r"^\s*limit = (\d+)\b", WORKFLOW.read_text(), re.M)
    assert literal, "the run-status retention limit is no longer a plain literal"
    assert int(literal.group(1)) == CHECKS_PER_DAY * (HISTORY_DAYS + 1)


def replay_day(day: str, outcome: str, dropped: set[int] = frozenset()) -> int:
    """Run a day of Worker ticks through the guard; return workflow runs started."""
    ticks = cron_arrivals()
    state: dict = {"history": []}
    runs: dict = {"history": []}
    started = 0
    for index, (utc_hour, minute) in enumerate(sorted(ticks)):
        if index in dropped:
            continue
        now = datetime.fromisoformat(f"{day}T{utc_hour:02d}:{minute:02d}:00+00:00")
        if not due(state, now, runs=runs)[0]:
            continue
        started += 1
        # Every started run logs an attempt, whether or not the check succeeds.
        runs["history"].append({"recorded_at": now.isoformat()})
        if outcome == "success":
            state["history"].append({"checked_at": now.isoformat()})
    return started


@pytest.mark.parametrize("day", ["2026-07-15", "2026-01-15"], ids=["PDT", "PST"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_never_more_than_eight_workflow_runs_a_day(day, outcome):
    """The hard ceiling: eight attempts a day, failures included."""
    assert replay_day(day, outcome) == len(RUN_HOURS) == 8


@pytest.mark.parametrize("dropped", [{0}, {0, 1}, set(range(0, 10, 2))], ids=["one", "two", "half"])
def test_dropped_worker_ticks_do_not_raise_the_ceiling(dropped):
    assert replay_day("2026-07-15", "failure", dropped) <= len(RUN_HOURS)
