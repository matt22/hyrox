# HYROX Anaheim ticket monitor

A deterministic Python 3 + Playwright monitor for these ticket categories only:

- Men's Open Singles
- Women's Open Singles
- Women's Open Doubles
- Mixed Open Doubles
- Mixed Open Relay

Charity, Adaptive, Pro, Spectator, and Youngstars tickets are explicitly excluded.

## How it works

GitHub Actions checks at **12:05 AM, 1:05 AM, and hourly from 7:05 AM through
12:05 PM Pacific time**. The workflow includes both UTC offsets and a Pacific-time
guard, so daylight-saving changes do not shift the requested local schedule.

The first successful run establishes a baseline. Later status changes post immediately
to one persistent GitHub issue and explicitly mention the repository owner, which
triggers GitHub's normal email notification. When there is no change, a status comment
is posted once at the end of each requested block: 1:05 AM and 12:05 PM Pacific.
Every successful check is committed to `state/current.json`, which retains the latest
two days' requested observations. The cap is derived from the configured Pacific run
hours (currently 8 per day, or 16 observations) rather than hardcoded. Successful
manual checks count toward the same cap; failed and schedule-guard-skipped runs do not
produce observations. Its metadata reports, per ticket category, both the number of
available observations and the number of transitions into availability during the
retained observations. `total_openings` provides a quick sum of all such opening
transitions still in the rolling history.
Unexpected page structures fail the job and upload
HTML, visible text, a screenshot, and error context as a 14-day diagnostic artifact.
Routine checks contain no AI calls; Codex can be used separately to inspect failures.

## Setup

1. In repository **Settings → Actions → General**, set **Workflow permissions** to
   **Read and write permissions**.
2. Enable email delivery in your GitHub notification settings. No email address or
   mailbox credential is stored in the repository.
3. Enable GitHub Actions and scheduled workflows for the repository.
4. Run **HYROX Anaheim availability** manually once to establish the baseline.

Notifications use restrained GitHub-Flavored Markdown: a clear callout, compact status
table, official event link, and timestamp. GitHub controls the surrounding email UI.

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
