# HYROX Anaheim ticket monitor

A deterministic Python 3 + Playwright monitor for these ticket categories only:

- Men's Open Singles
- Women's Open Singles
- Women's Open Doubles
- Mixed Open Doubles
- Mixed Open Relay

Charity, Adaptive, Pro, Spectator, and Youngstars tickets are explicitly excluded.

## How it works

The monitor attempts one check in each of eight Pacific hours: midnight, 1 AM, and hourly
from 7 AM through noon. That is a ceiling, not a target — the workflow never runs more than
eight times a day.

The workflow has no cron of its own. GitHub delivers `schedule` events on a best-effort
basis — this repo was receiving roughly a quarter of them, 30-60 minutes late — so
holding to eight runs a day through GitHub's scheduler is not possible: covering every
Pacific hour would mean requesting far more arrivals than needed and turning most away,
each one a run on the Actions log. The trigger is the Cloudflare Worker in
[`cloudflare/`](cloudflare/) instead: its cron lists the eight Pacific run hours directly,
each at :05, as UTC — unioned across both DST offsets, since a fixed UTC hour means a
different Pacific hour in summer than in winter — and dispatches the workflow only for a
Pacific hour that has neither an observation nor a logged attempt.

`schedule.py` applies the same two rules again when the run starts, before anything is
installed, so the ceiling holds no matter what does the dispatching — including a
repeated manual dispatch. An hour is spent as soon as an attempt is logged for it: a
failed check is written to `state/run-status.json` and shown on the dashboard as a
failure marker rather than retried.

`RUN_HOURS` in `schedule.py` is the only definition of the schedule. Because the guard
reads the wall clock in `America/Los_Angeles`, the cadence needs no adjustment across
daylight saving; the earlier fixed-UTC cron silently lost an hour every summer.

The first successful run establishes a baseline. Later status changes post immediately
to one persistent GitHub issue and explicitly mention the repository owner, which
triggers GitHub's normal email notification. When there is no change, a status comment
is posted once at the end of each requested block: the 1 AM and noon Pacific checks.
Every successful check is committed to `state/current.json`, which retains the latest
16 observations: eight checks per day for two days. The dashboard renders that full
rolling history and labels it with the rate actually achieved, so a day that ran short
shows as such instead of being presented as a full window. Successful manual checks
count toward the same cap; failed runs do not produce observations. Its metadata
reports, per ticket category, both the number of available observations and the
number of transitions into availability during the retained observations.
`total_openings` provides a quick sum of all such opening transitions still in the
rolling history.
Unexpected page structures fail the job and upload
HTML, visible text, a screenshot, and error context as a 14-day diagnostic artifact.
Every attempt also commits `state/run-status.json`, which retains the latest
24 of them, failures included,
so the dashboard can warn that its availability display is the last known good state
and represent failures in the history table with links to their Actions runs.
Routine checks contain no AI calls; Codex can be used separately to inspect failures.

## Setup

1. In repository **Settings → Actions → General**, set **Workflow permissions** to
   **Read and write permissions**.
2. Enable email delivery in your GitHub notification settings. No email address or
   mailbox credential is stored in the repository.
3. Enable GitHub Actions and scheduled workflows for the repository.
4. Run **HYROX Anaheim availability** manually once to establish the baseline.

Notifications use restrained GitHub-Flavored Markdown: a clear callout, compact status
table, official event link, and timestamp. An availability opening is headed
`🟢 TICKETS AVAILABLE` and begins with a green attention marker. The persistent issue
is titled `🟢 HYROX Anaheim ticket monitor`, so GitHub's notification-email subject
also carries the green-circle icon. GitHub controls the remaining email UI.

To mention more accounts later, add a repository variable named `HYROX_NOTIFY_USERS`
containing comma-separated GitHub usernames and expose it to the render step. The
default recipient is the repository owner (`matt22`).

## Local use

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
pytest -q
python monitor.py
```

Override the source page with `HYROX_TICKET_URL` or `--url` if HYROX changes the
canonical Vivenu ticket-shop URL.

## Dashboard

The repository includes a static Tailwind dashboard for `state/current.json`. No
JavaScript framework or build step is required. Run it locally from the repository
root:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/`.
