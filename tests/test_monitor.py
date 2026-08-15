from datetime import datetime, timezone

import pytest

from monitor import (
    HISTORY_DAYS, RUN_HOURS, StructureError, block_summary_due, changes,
    parse_ticket_texts, requested_history_limit, rolling_state, scheduled_now,
)
from notify import notification_users, render_markdown


BLOCKS = [
    "Men's Open Singles Saturday - Sold Out",
    "Women's Open Singles Friday - Buy now",
    "Women's Open Doubles Sunday - Unavailable",
    "Mixed Open Doubles Saturday - Select tickets",
    "Mixed Open Relay Friday - Available",
    "Men's Pro Singles - Buy now",
    "Women's Charity Singles - Buy now",
    "Spectator tickets - Buy now",
]


def test_only_tracks_requested_categories():
    result = parse_ticket_texts(BLOCKS)
    assert list(result) == [
        "Men's Open Singles", "Women's Open Singles", "Women's Open Doubles",
        "Mixed Open Doubles", "Mixed Open Relay",
    ]
    assert result["Men's Open Singles"].status == "unavailable"
    assert result["Women's Open Singles"].status == "available"


def test_missing_category_is_unexpected_structure():
    with pytest.raises(StructureError):
        parse_ticket_texts(BLOCKS[:-4])


def test_unknown_availability_wording_is_unexpected_structure():
    with pytest.raises(StructureError, match="wording"):
        parse_ticket_texts([line.replace("Buy now", "Details") for line in BLOCKS])


def test_changes_ignore_evidence_and_timestamps():
    old = {"tickets": {"Mixed Open Relay": {"status": "unavailable", "evidence": "old"}}}
    new = {"tickets": {"Mixed Open Relay": {"status": "available", "evidence": "new"}}}
    assert changes(old, new) == ["Mixed Open Relay: unavailable -> available"]


def observation(checked_at, status):
    return {
        "checked_at": checked_at,
        "event": "Centr HYROX Anaheim 2026",
        "source_url": "https://example.com",
        "tickets": {
            name: {"status": status, "evidence": "test"}
            for name in (
                "Men's Open Singles", "Women's Open Singles", "Women's Open Doubles",
                "Mixed Open Doubles", "Mixed Open Relay",
            )
        },
    }


def test_rolling_state_migrates_legacy_state_and_counts_openings():
    old = observation("2026-08-15T08:00:00+00:00", "unavailable")
    current = observation("2026-08-15T09:00:00+00:00", "available")
    state = rolling_state(old, current)
    assert state["meta"]["observation_count"] == 2
    assert state["meta"]["total_openings"] == len(state["meta"]["openings"])
    assert state["meta"]["openings"]["Mixed Open Relay"] == {
        "available_observations": 1,
        "opening_transitions": 1,
    }


def test_first_available_observation_is_not_a_transition():
    state = rolling_state(None, observation("2026-08-15T09:00:00+00:00", "available"))
    assert state["meta"]["openings"]["Mixed Open Relay"] == {
        "available_observations": 1,
        "opening_transitions": 0,
    }


def test_history_limit_is_derived_from_requested_runs():
    assert requested_history_limit() == len(RUN_HOURS) * HISTORY_DAYS


def test_rolling_state_evicts_only_the_oldest_observation_at_the_limit():
    state = None
    for hour in range(requested_history_limit() + 1):
        current = observation(f"2026-08-15T{hour:02d}:00:00+00:00", "unavailable")
        state = rolling_state(state, current)
    assert state["meta"]["observation_count"] == requested_history_limit()
    assert state["meta"]["max_observations"] == requested_history_limit()
    assert state["history"][0]["checked_at"] == "2026-08-15T01:00:00+00:00"


def test_total_openings_decrements_when_opening_observation_is_evicted():
    state = rolling_state(None, observation("2026-08-15T00:00:00+00:00", "unavailable"), limit=2)
    state = rolling_state(state, observation("2026-08-15T01:00:00+00:00", "available"), limit=2)
    assert state["meta"]["total_openings"] == len(state["meta"]["openings"])

    state = rolling_state(state, observation("2026-08-15T02:00:00+00:00", "available"), limit=2)
    assert state["meta"]["total_openings"] == len(state["meta"]["openings"])

    state = rolling_state(state, observation("2026-08-15T03:00:00+00:00", "unavailable"), limit=2)
    assert state["meta"]["total_openings"] == 0


@pytest.mark.parametrize("utc_hour, expected", [(7, True), (8, True), (14, True), (19, True), (20, False)])
def test_schedule_guard_during_daylight_time(utc_hour, expected):
    now = datetime(2026, 8, 15, utc_hour, 5, tzinfo=timezone.utc)
    assert scheduled_now(now) is expected


@pytest.mark.parametrize("utc_hour, expected", [(8, True), (9, True), (15, True), (20, True), (21, False)])
def test_schedule_guard_during_standard_time(utc_hour, expected):
    now = datetime(2026, 12, 15, utc_hour, 5, tzinfo=timezone.utc)
    assert scheduled_now(now) is expected


def test_summary_is_due_only_at_block_endpoints():
    assert block_summary_due(datetime(2026, 8, 15, 8, 5, tzinfo=timezone.utc))  # 1:05 AM PDT
    assert block_summary_due(datetime(2026, 8, 15, 19, 5, tzinfo=timezone.utc))  # 12:05 PM PDT
    assert not block_summary_due(datetime(2026, 8, 15, 18, 5, tzinfo=timezone.utc))


def test_github_notification_template():
    state = {
        "checked_at": "2026-08-15T19:05:00+00:00",
        "source_url": "https://example.com/?a=1&b=2",
        "tickets": {"<Mixed>": {"status": "available", "evidence": "ignored"}},
    }
    rendered = render_markdown(state, ["Mixed Open Relay: unavailable -> available"], ["matt22"])
    assert rendered.startswith("@matt22")
    assert "## Availability changed" in rendered
    assert "✅ **AVAILABLE**" in rendered
    assert "https://example.com/?a=1&b=2" in rendered


def test_notification_users_are_validated_and_deduplicated():
    assert notification_users("@matt22, second-user, matt22") == ["matt22", "second-user"]
    with pytest.raises(ValueError):
        notification_users("not valid!")
