# Event registry

`events.json` is a registry of HYROX events, keyed by `<city-slug>-<year>`. It
drives `monitor.py`, `schedule.py`, the workflow, the Cloudflare Worker and the
dashboard: every `active` event with a `source_url` is checked on its own
schedule, with its state in `state/<event-key>/`.

## Fields

- `name` — official event name, including any title sponsor.
- `city`, `year` — for display and the registry key.
- `timezone` — IANA zone for the event's **own local time** (e.g.
  `America/Denver` for a Mountain-time race). Each event's `run_hours` and
  stop date are interpreted in it.
- `venue`, `event_dates` — informational; not consumed by any script.
- `first_competition_date` — `YYYY-MM-DD`. Checks stop 5 days before it, in the
  event's own timezone, and the dashboard counts days out from it.
- `event_url` — the official hyrox.com event page. The dashboard's upcoming
  events list links here, so fill it in even before tickets go on sale.
- `source_url` — the Vivenu ticket-shop URL `monitor.py` scrapes. `null`
  until tickets go on sale; a monitored event needs this.
- `first_ticket_sale_date` — the date general tickets first went (or are
  predicted to go) on sale, `YYYY-MM-DD`. `null` if not yet known.
- `first_ticket_sale_date_confirmed` — `true` once the date is a known fact
  (e.g. observed going live, or officially announced); `false` while it's
  a prediction. Correct both fields as better info comes in — a prediction
  is expected to be wrong and gets overwritten, not preserved for history.
- `divisions_tracked` — ticket categories to watch, matching the exclusions
  in the main README (Charity/Adaptive/Pro/Spectator/Youngstars excluded).
- `run_hours` — hours (0–23) in the event's own `timezone` to attempt one
  check in, mirroring `RUN_HOURS` in `schedule.py`.
- `status` — `active` (currently monitored), or `upcoming` (staged, no
  `source_url` yet).
- `notify_users` — GitHub usernames to mention on availability changes.
- `is_default` — which event the dashboard opens on and `monitor.py` checks
  without `--event`. Exactly one entry should be `true`.

## Adding an event

Fill in every field above. Leave `source_url: null` and `status: "upcoming"`
until the official event page has a live ticket link — without it there's
nothing for the monitor to check.

To start monitoring: set `source_url` to the canonical
`https://usa.hyrox.com/events/...` shop URL and `status: "active"`, then
dispatch the workflow once with **event** set to its key to record a
baseline. If its timezone isn't Pacific/Arizona, check that the Worker's cron
in `cloudflare/wrangler.toml` still reaches its run hours (a test enforces this).
