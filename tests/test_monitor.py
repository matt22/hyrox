from datetime import datetime, timezone

import pytest

from monitor import StructureError, block_summary_due, changes, parse_ticket_texts, scheduled_now
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
