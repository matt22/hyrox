from datetime import datetime, timezone

import pytest

from monitor import (
    StructureError, changes, issue_title, parse_ticket_texts, record_openings, requested_history_limit,
    rolling_state,
)
from notify import notification_users, render_markdown
from schedule import CHECKS_PER_DAY, HISTORY_DAYS, block_summary_due


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


def test_history_limit_is_eight_checks_per_day_for_two_days():
    assert requested_history_limit() == CHECKS_PER_DAY * HISTORY_DAYS == 16


def test_rolling_state_evicts_only_the_oldest_observation_at_the_limit():
    state = None
    for hour in range(requested_history_limit() + 1):
        current = observation(f"2026-08-15T{hour:02d}:00:00+00:00", "unavailable")
        state = rolling_state(state, current)
    assert state["meta"]["observation_count"] == requested_history_limit()
    assert state["meta"]["max_observations"] == requested_history_limit()
    assert state["history"][0]["checked_at"] == "2026-08-15T01:00:00+00:00"


def test_total_openings_decrements_when_opening_observation_is_evicted():
    state = rolling_state(None, observation("2026-08-15T00:00:00+00:00", "unavailable"))
    state = rolling_state(state, observation("2026-08-15T01:00:00+00:00", "available"))
    assert state["meta"]["total_openings"] == len(state["meta"]["openings"])

    for hour in range(2, requested_history_limit() + 1):
        state = rolling_state(state, observation(f"2026-08-15T{hour:02d}:00:00+00:00", "available"))
    assert state["meta"]["total_openings"] == len(state["meta"]["openings"])

    state = rolling_state(state, observation("2026-08-16T00:00:00+00:00", "unavailable"))
    assert state["meta"]["total_openings"] == 0


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
    assert "## 🟢 TICKETS AVAILABLE" in rendered
    assert "🟢 **Tickets are available now — act quickly.**" in rendered
    assert "✅ **AVAILABLE**" in rendered
    assert "https://example.com/?a=1&b=2" in rendered


def test_notification_users_are_validated_and_deduplicated():
    assert notification_users("@matt22, second-user, matt22") == ["matt22", "second-user"]
    with pytest.raises(ValueError):
        notification_users("not valid!")


def test_record_openings_keeps_available_checks_forever_without_duplicates():
    archive = record_openings(None, observation("2026-08-15T00:00:00+00:00", "unavailable"))
    assert archive == {"openings": []}
    found = observation("2026-08-15T01:00:00+00:00", "available")
    archive = record_openings(archive, found)
    archive = record_openings(archive, found)
    for hour in range(2, 40):
        archive = record_openings(archive, observation(f"2026-08-{15 + hour // 24}T{hour % 24:02d}:00:00+00:00", "unavailable"))
    assert [item["checked_at"] for item in archive["openings"]] == ["2026-08-15T01:00:00+00:00"]


def test_an_event_can_track_a_subset_of_divisions():
    result = parse_ticket_texts(BLOCKS[:2], ["Men's Open Singles", "Women's Open Singles"])
    assert list(result) == ["Men's Open Singles", "Women's Open Singles"]


def test_an_untracked_division_name_is_rejected_rather_than_ignored():
    with pytest.raises(ValueError, match="Men's Elite"):
        parse_ticket_texts(BLOCKS, ["Men's Elite Singles"])


def test_each_event_gets_its_own_issue_and_anaheim_keeps_its_existing_one():
    assert issue_title({"city": "Anaheim"}) == "🟢 HYROX Anaheim ticket monitor"
    assert issue_title({"city": "Phoenix"}) == "🟢 HYROX Phoenix ticket monitor"


def test_notification_names_the_event():
    state = {
        "event": "InBody HYROX Phoenix 2027",
        "checked_at": "2026-10-08T19:05:00+00:00",
        "source_url": "https://example.com",
        "tickets": {},
    }
    assert "official InBody HYROX Phoenix 2027 event page" in render_markdown(state, [], ["matt22"])
