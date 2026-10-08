/**
 * Primary trigger for the HYROX ticket monitor.
 *
 * GitHub's own `schedule` events are best-effort and this repo has been getting
 * roughly a quarter of them, 30-60 minutes late, so the workflow has no cron of
 * its own. The schedule lives here instead: the Worker's cron trigger in
 * wrangler.toml lists RUN_HOURS' eight Pacific hours directly, each at :05, as
 * UTC — unioned across both DST offsets, since a fixed UTC hour means a
 * different Pacific hour in PDT than in PST. Ten UTC hours cover the eight
 * Pacific ones across both seasons; on any given day two of those ticks fall
 * outside RUN_HOURS for the season in effect and are cheap no-ops.
 *
 * `scheduled()` below still exists to dispatch only for a Pacific hour that
 * has neither an observation nor a logged attempt, and it still checks
 * RUN_HOURS first — not because the cron might tick outside them (it won't,
 * by construction), but because it's the single source of truth for whether a
 * given tick's Pacific hour should dispatch at all, independent of what the
 * cron string happens to contain. That caps GitHub at eight runs a day. A
 * dropped tick here costs that hour's check for the day; Cloudflare does not
 * retry a failed tick, and there is no later tick in the same hour to fall
 * back on.
 *
 * Every active event in config/events.json is considered on each tick, in its
 * own timezone and run hours, against its own state/<event-key>/ files; one
 * dispatch covers all of them, and schedule.py picks which are due. An event
 * past its stop date (STOP_DAYS_BEFORE_COMPETITION in schedule.py) no longer
 * counts, so it can't keep dispatching runs that schedule.py turns away.
 *
 * Deliberately duplicates the guard from schedule.py rather than importing it:
 * the Worker decides whether to spend a dispatch, and schedule.py independently
 * decides whether to spend a check. Either one alone keeps the hour from being
 * checked twice.
 */

// Fallbacks for registry entries that omit them; mirror schedule.py.
const RUN_HOURS = [0, 1, 7, 8, 9, 10, 11, 12];
const DEFAULT_ZONE = 'America/Los_Angeles';
const STOP_DAYS_BEFORE_COMPETITION = 5;
// Mirrors MAX_ATTEMPTS_PER_HOUR in schedule.py: one attempt per run hour, so
// the workflow runs at most eight times a day per event. An hour is spent as
// soon as an attempt is logged for it, successful or not — a failed check is
// recorded in run-status.json and shown on the dashboard rather than retried.
const MAX_ATTEMPTS_PER_HOUR = 1;
const OWNER = 'matt22';
const REPO = 'hyrox';
const WORKFLOW = 'monitor.yml';
const BRANCH = 'main';
const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}`;
const EVENTS_URL = `${RAW}/config/events.json`;
const API = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
const UA = `${OWNER}-hyrox-monitor`;

/** The local hour an instant falls in, in an IANA zone, as `2026-09-13T10`. */
function hourKey(date, timeZone = DEFAULT_ZONE) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hour12: false,
  }).formatToParts(date).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  // en-CA renders midnight as hour 24; the date part has already rolled over.
  const hour = parts.hour === '24' ? '00' : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day}T${hour}`;
}

const localHour = (date, timeZone) => Number(hourKey(date, timeZone).slice(-2));
const zoneOf = (event) => event.timezone || DEFAULT_ZONE;
const runHoursOf = (event) => event.run_hours || RUN_HOURS;

/** Whether `date` is on or after the event's stop date, in its own zone. */
function stopped(date, event) {
  if (!event.first_competition_date) return false;
  const stop = new Date(`${event.first_competition_date}T00:00:00Z`);
  stop.setUTCDate(stop.getUTCDate() - STOP_DAYS_BEFORE_COMPETITION);
  return hourKey(date, zoneOf(event)).slice(0, 10) >= stop.toISOString().slice(0, 10);
}

/** Active events (with a ticket shop) whose own run hours include `date`. */
export function inRunHours(events, date) {
  return Object.entries(events).filter(([, event]) =>
    event.status === 'active' && event.source_url
    && runHoursOf(event).includes(localHour(date, zoneOf(event)))
    && !stopped(date, event));
}

// raw.githubusercontent is CDN-cached for a few minutes, so these can be stale.
// A duplicate dispatch is harmless: schedule.py applies both rules again.
async function readJson(url) {
  const response = await fetch(url, { headers: { 'user-agent': UA } });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${url} fetch failed: ${response.status}`);
  return response.json();
}

async function coverage(key, timeZone) {
  const [state, runs] = await Promise.all([
    readJson(`${RAW}/state/${key}/current.json`),
    readJson(`${RAW}/state/${key}/run-status.json`),
  ]);
  const checked = new Set((state?.history || []).map((o) => hourKey(new Date(o.checked_at), timeZone)));
  const attempts = new Map();
  for (const attempt of runs?.history || []) {
    const hour = hourKey(new Date(attempt.recorded_at), timeZone);
    attempts.set(hour, (attempts.get(hour) || 0) + 1);
  }
  return { checked, attempts };
}

async function dispatch(token) {
  const response = await fetch(API, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`,
      accept: 'application/vnd.github+json',
      'x-github-api-version': '2022-11-28',
      'user-agent': UA,
      'content-type': 'application/json',
    },
    body: JSON.stringify({ ref: BRANCH }),
  });
  if (!response.ok) throw new Error(`dispatch failed: ${response.status} ${await response.text()}`);
}

/** Whether one event, already known to be in its run hours, still needs this hour's check. */
export function decide(now, { checked, attempts }, timeZone = DEFAULT_ZONE) {
  const key = hourKey(now, timeZone);
  if (checked.has(key)) return { dispatch: false, reason: `${key} already recorded` };
  const attempted = attempts.get(key) || 0;
  if (attempted >= MAX_ATTEMPTS_PER_HOUR) {
    return { dispatch: false, reason: `${key} already used its attempt` };
  }
  return { dispatch: true, reason: `no check recorded for ${key} ${timeZone}` };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      const now = new Date(event.scheduledTime);
      const candidates = inRunHours((await readJson(EVENTS_URL)) || {}, now);
      let due = false;
      for (const [key, item] of candidates) {
        const decision = decide(now, await coverage(key, zoneOf(item)), zoneOf(item));
        console.log(`${key}: ${decision.dispatch ? 'due' : 'skipping'} — ${decision.reason}`);
        due ||= decision.dispatch;
      }
      if (!candidates.length) console.log(`${now.toISOString()}: no active event in its run hours`);
      if (due) await dispatch(env.GITHUB_TOKEN);
    })());
  },
};
