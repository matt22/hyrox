# Cloudflare trigger

The scheduler for the monitor. The GitHub workflow has **no `schedule:` trigger** —
GitHub delivers cron slots on a best-effort basis and this repo was receiving roughly a
quarter of them, 30-60 minutes late, so covering every Pacific hour through GitHub's
scheduler would mean requesting far more arrivals than needed and turning most away.
This Worker dispatches the workflow instead, once per Pacific run hour.

The Worker's cron trigger lists `RUN_HOURS`' eight Pacific hours directly, each at :05, as
UTC hours — unioned across both DST offsets (PDT and PST map the same eight Pacific hours
to different UTC hours), for ten distinct UTC hours total. On any given day, eight of those
ten ticks fall in a Pacific run hour for the season in effect and the other two are cheap
no-ops, so no separate winter/summer schedule is needed. The Worker still checks
`RUN_HOURS` on every tick, reads `state/current.json` and `state/run-status.json` to see
whether the current Pacific hour already has an observation or a logged attempt, and
dispatches only when it has neither. GitHub therefore runs the workflow **at most eight
times a day**, each five minutes after its Pacific run hour starts. A tick Cloudflare drops
costs that hour's check for the day — Cloudflare does not retry a failed tick, and there is
no later tick in the same hour to fall back on.

`schedule.py` re-applies both rules when the run starts, so the ceiling holds even if
this Worker misbehaves or someone dispatches the workflow by hand in a loop. The two
implementations are kept in step by a differential test over 1,360 scenarios.

## Free-plan headroom

| Limit | Used |
| --- | --- |
| 100,000 requests/day (cron ticks count) | 10 |
| 5 cron triggers per account | 1 |
| 10 ms CPU per invocation (I/O wait excluded) | two fetches, small JSON parse |
| 50 subrequests per invocation | 2 |

## Deploy

1. Create a [fine-grained GitHub token](https://github.com/settings/personal-access-tokens/new)
   scoped to this repository only, with **Actions: read and write**. Nothing else.
2. From this directory:

```bash
npx wrangler secret put GITHUB_TOKEN
```

```bash
npx wrangler deploy
```

3. Confirm it is ticking — one line per tick, and the reason it did or did not dispatch:

```bash
npx wrangler tail hyrox-monitor-trigger --format pretty
```

To rotate the token, re-run `wrangler secret put GITHUB_TOKEN`. If the Worker is deleted
or its token expires the monitor simply stops until it is restored; nothing else triggers
it. `state/run-status.json` and the dashboard's check-rate label make that visible.
