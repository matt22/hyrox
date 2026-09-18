# Event registry

`events.json` is a registry of HYROX events, keyed by `<city-slug>-<year>`. It is
not yet read by `monitor.py`, `schedule.py`, or the Cloudflare Worker — those
still monitor Anaheim only, on a hardcoded Pacific schedule. This file exists
so the data is staged ahead of that work.

## Fields

- `name` — official event name, including any title sponsor.
- `city`, `year` — for display and the registry key.
- `timezone` — IANA zone for the event's **own local time** (e.g.
  `America/Denver` for a Mountain-time race), not the repo's current Pacific
  default. Once per-event scheduling lands, this is what each event's
  `run_hours` will be interpreted in.
- `venue`, `event_dates` — informational; not consumed by any script.
- `source_url` — the Vivenu ticket-shop URL `monitor.py` scrapes. `null`
  until tickets go on sale; a monitored event needs this.
- `divisions_tracked` — ticket categories to watch, matching the exclusions
  in the main README (Charity/Adaptive/Pro/Spectator/Youngstars excluded).
- `run_hours` — hours (0–23) in the event's own `timezone` to attempt one
  check in, mirroring `RUN_HOURS` in `schedule.py`.
- `status` — `active` (currently monitored), or `upcoming` (staged, no
  `source_url` yet).
- `notify_users` — GitHub usernames to mention on availability changes.
- `is_default` — which event backs the dashboard while only one event is
  monitored at a time. Exactly one entry should be `true`.

## Adding an event

Fill in every field above. Leave `source_url: null` and `status: "upcoming"`
until the official event page has a live ticket link — without it there's
nothing for the monitor to check.
