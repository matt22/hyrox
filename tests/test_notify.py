"""The combined notification: one comment per run, covering every active event."""

import json
from datetime import date

import pytest

from notify import (
    ISSUE_TITLE, collect_rows, date_range, event_row, notification_users, render_markdown,
    should_notify,
)

DIVISIONS = ["Men's Open Singles", "Women's Open Doubles"]
TODAY = date(2026, 10, 12)


def event(city, **extra):
    return {
        "city": city, "year": 2027, "status": "active", "source_url": "https://example.com",
        "first_competition_date": "2027-02-25", "divisions_tracked": DIVISIONS, **extra,
    }


def observation(*available):
    return {"tickets": {
        name: {"status": "available" if name in available else "unavailable"} for name in DIVISIONS
    }}


def row(city, obs=None, result=None, **extra):
    return event_row(city.lower(), event(city, **extra), obs, result, TODAY, None)


def test_one_issue_for_every_event():
    assert ISSUE_TITLE == "🟢 HYROX ticket monitor"


def test_openings_lead_the_heading_and_callout_with_their_city():
    rows = [
        row("Anaheim", observation()),
        row("Phoenix", observation("Women's Open Doubles"),
            {"outcome": "success", "changes": ["Women's Open Doubles: unavailable -> available"]}),
    ]
    rendered = render_markdown(rows, ["matt22"])
    assert rendered.startswith("@matt22")
    assert "## 🟢 TICKETS AVAILABLE — Phoenix\n" in rendered
    assert "**Phoenix**: Women's Open Doubles: unavailable -> available" in rendered
    assert "| ✅ 1 / 2 | Women's Open Doubles |" in rendered
    # The open event sorts above the quiet one.
    assert rendered.index("[Phoenix 2027]") < rendered.index("[Anaheim 2027]")


def test_a_closing_alone_is_an_availability_change():
    rows = [row("Anaheim", observation(), {"outcome": "success",
                                           "changes": ["Men's Open Singles: available -> unavailable"]})]
    rendered = render_markdown(rows, ["matt22"])
    assert "## Availability changed — Anaheim" in rendered
    assert "TICKETS AVAILABLE" not in rendered


def test_a_quiet_run_renders_the_daily_summary():
    rendered = render_markdown([row("Anaheim", observation())], ["matt22"])
    assert "## Daily status summary" in rendered
    assert "| 0 / 2 | None open |" in rendered


def test_presale_and_failed_events_get_one_row_each():
    presale = row("Vegas", None, source_url=None, first_ticket_sale_date="2026-11-20",
                  first_ticket_sale_date_confirmed=False)
    failed = row("Phoenix", observation(), {"outcome": "failure", "changes": []})
    rendered = render_markdown([presale, failed], ["matt22"], run_url="https://run")
    assert "| — | Pre-sale · sale ~Nov 20 |" in rendered
    assert "[⚠️ Check failed](https://run)" in rendered


def test_rows_link_to_each_events_dashboard_page():
    assert row("Anaheim", is_default=True)["url"] == "https://matt22.github.io/hyrox/"
    assert row("Phoenix")["url"] == "https://matt22.github.io/hyrox/?event=phoenix"


def test_dates_read_as_a_short_range():
    assert date_range({"event_dates": "2027-02-25 to 2027-02-28"}) == "Feb 25–28"
    assert date_range({"event_dates": "2027-02-27 to 2027-03-02"}) == "Feb 27–Mar 2"
    assert date_range({"first_competition_date": "2026-12-03"}) == "Dec 3"


def test_notify_only_on_a_change_or_the_daily_summary():
    quiet = [row("Anaheim", observation(), {"outcome": "success", "changes": []})]
    assert not should_notify(quiet, summary_due=False)
    assert should_notify(quiet, summary_due=True)
    changed = [row("Anaheim", observation(), {"outcome": "success", "changes": ["x -> available"]})]
    assert should_notify(changed, summary_due=False)


def test_collect_rows_combines_results_with_every_active_events_state(tmp_path):
    config = tmp_path / "events.json"
    config.write_text(json.dumps({
        "anaheim": event("Anaheim", first_competition_date="2026-12-03"),
        "phoenix": event("Phoenix"),
        "vegas": event("Vegas", source_url=None),
        "portland": event("Portland", status="upcoming"),
    }))
    for key, obs in {"anaheim": observation(), "phoenix": observation("Men's Open Singles")}.items():
        (tmp_path / "state" / key).mkdir(parents=True)
        (tmp_path / "state" / key / "current.json").write_text(json.dumps({"history": [obs]}))
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "phoenix.json").write_text(json.dumps(
        {"event": "phoenix", "outcome": "success", "changes": ["Men's Open Singles: unavailable -> available"]}
    ))
    rows = {r["key"]: r for r in collect_rows(config, tmp_path / "state", tmp_path / "results")}
    assert set(rows) == {"anaheim", "phoenix", "vegas"}
    assert rows["phoenix"]["open"] == ["Men's Open Singles"] and rows["phoenix"]["changes"]
    assert rows["anaheim"]["changes"] == [] and rows["vegas"]["open_cell"] == "—"


def test_notification_users_are_validated_and_deduplicated():
    assert notification_users("@matt22, second-user, matt22") == ["matt22", "second-user"]
    with pytest.raises(ValueError):
        notification_users("not valid!")
