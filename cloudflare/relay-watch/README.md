# Mixed Relay watcher

A separate Cloudflare Worker that checks **HYROX San Diego Mixed Relay** once a minute
and alerts your phone the moment a day becomes buyable. It is independent of the
monitor's dispatch Worker in [`../`](../) (eight browser checks a day): its own
`wrangler.toml`, cron, KV namespace and secrets. Deploying or removing it never touches
the monitor, its workflow or `state/`.

## What it checks

One `GET https://vivenu.com/api/events/info/<EVENT_ID>` a minute. That public JSON is
the data the ticket shop itself renders from. No HTML scraping, no browser, no AI.

- **Bought or not:** a day is available when `min(ticket.v, category.v) > 0`, the same
  remaining-volume rule that enables the shop's add-to-cart button. `active` is not
  used: sold-out tickets stay `active: true`.
- **Which ticket:** HYROX's machine key `meta.competition_class_matching_key ==
  "RELAY_X"` **or** the name `HYROX MIXED RELAY | <day>`. Team-member tickets
  (three are auto-added per team) are reported so the alert can warn if a team of
  four won't fit. Charity, Pro and Adaptive variants never count. New days
  (Saturday/Sunday) are picked up automatically.
- **When HYROX changes something:** if neither identifier finds a Mixed Relay
  ticket, the volume field disappears, or Vivenu is unreachable for 10 minutes, you
  get one "watcher can't read tickets" notice and another when it recovers. Silence
  never stands in for "sold out".

It alerts once per opening, re-arms when the day sells out again, retries on the
next minute if no channel delivered, and stops after `STOP_AFTER`.

## Alert channels

Set either one or both, as Worker secrets. Each is used only when its secrets exist.

| Channel | Secrets | Notes |
| --- | --- | --- |
| Pushover push | `PUSHOVER_TOKEN`, `PUSHOVER_USER` | Works immediately. Openings send at high priority (sound during quiet hours). |
| Twilio SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `ALERT_TO` | US carriers require a registered sending number (toll-free verification or 10DLC) before texts deliver reliably. `TWILIO_FROM` may be a number or a Messaging Service SID (`MG…`). |

## Deploy

From this folder, logged in with `npx wrangler login`:

```sh
# 1. State store; paste the printed id into wrangler.toml ([[kv_namespaces]] id)
npx wrangler kv namespace create RELAY_WATCH_STATE

# 2. Confirm your phone gets alerts before deploying
PUSHOVER_TOKEN=… PUSHOVER_USER=… node send-test-alert.js

# 3. Secrets for the channel(s) you use
npx wrangler secret put PUSHOVER_TOKEN
npx wrangler secret put PUSHOVER_USER

# 4. Deploy and watch the first few checks (e.g. "Friday=0")
npx wrangler deploy
npx wrangler tail hyrox-relay-watch
```

To stop it: `npx wrangler delete hyrox-relay-watch`.

To watch a different event, change `EVENT_ID` (the id in the shop's
`usa.hyrox.com/tickets/<id>` URL), `EVENT_NAME`, `SHOP_URL` and `STOP_AFTER` in
`wrangler.toml`.

## Limits (free plan)

| Limit | Used |
| --- | --- |
| 100,000 requests/day | 1,440 |
| 5 cron triggers per account | 1 (the monitor uses another) |
| 1,000 KV writes/day | only on changes |
| 10 ms CPU per invocation | one ~250 KB JSON parse; network wait doesn't count |

If `wrangler tail` shows "exceeded CPU" errors, move to the Workers paid plan
($5/month), which raises the CPU limit.

## Tests

```sh
npm test   # node --test, no dependencies
```
