/**
 * Primary trigger for the HYROX ticket monitor.
 *
 * GitHub's own `schedule` events are best-effort and this repo has been getting
 * roughly a quarter of them, 30-60 minutes late, so the workflow has no cron of
 * its own. The schedule lives here instead: tick every ten minutes, and dispatch
 * the workflow only for a Pacific hour that has neither an observation nor a
 * logged attempt. That caps GitHub at eight runs a day while still covering an
 * hour whose first tick was missed — which matters, because Cloudflare does not
 * retry a failed tick either.
 *
 * Deliberately duplicates RUN_HOURS from schedule.py rather than importing it:
 * the Worker decides whether to spend a dispatch, and schedule.py independently
 * decides whether to spend a check. Either one alone keeps the hour from being
 * checked twice.
 */

const RUN_HOURS = [1, 6, 7, 8, 9, 10, 11, 12];
// Mirrors MAX_ATTEMPTS_PER_HOUR in schedule.py: one attempt per run hour, so
// the workflow runs at most eight times a day. An hour is spent as soon as an
// attempt is logged for it, successful or not — a failed check is recorded in
// state/run-status.json and shown on the dashboard rather than retried.
const MAX_ATTEMPTS_PER_HOUR = 1;
const OWNER = 'matt22';
const REPO = 'hyrox';
const WORKFLOW = 'monitor.yml';
const BRANCH = 'main';
const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/state`;
const STATE_URL = `${RAW}/current.json`;
const RUNS_URL = `${RAW}/run-status.json`;
const API = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
const UA = `${OWNER}-hyrox-monitor`;

/** The Pacific hour an instant falls in, as `2026-09-13T10`. */
function hourKey(date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Los_Angeles',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hour12: false,
  }).formatToParts(date).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  // en-CA renders midnight as hour 24; the date part has already rolled over.
  const hour = parts.hour === '24' ? '00' : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day}T${hour}`;
}

function pacificHour(date) {
  return Number(hourKey(date).slice(-2));
}

// raw.githubusercontent is CDN-cached for a few minutes, so these can be stale.
// A duplicate dispatch is harmless: schedule.py applies both rules again.
async function readState(url) {
  const response = await fetch(url, { headers: { 'user-agent': UA } });
  if (response.status === 404) return { history: [] };
  if (!response.ok) throw new Error(`${url} fetch failed: ${response.status}`);
  return response.json();
}

async function coverage() {
  const [state, runs] = await Promise.all([readState(STATE_URL), readState(RUNS_URL)]);
  const checked = new Set((state.history || []).map((o) => hourKey(new Date(o.checked_at))));
  const attempts = new Map();
  for (const attempt of runs.history || []) {
    const key = hourKey(new Date(attempt.recorded_at));
    attempts.set(key, (attempts.get(key) || 0) + 1);
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

export function decide(now, { checked, attempts }) {
  const key = hourKey(now);
  if (!RUN_HOURS.includes(pacificHour(now))) return { dispatch: false, reason: 'outside run hours' };
  if (checked.has(key)) return { dispatch: false, reason: `${key} already recorded` };
  const attempted = attempts.get(key) || 0;
  if (attempted >= MAX_ATTEMPTS_PER_HOUR) {
    return { dispatch: false, reason: `${key} already used its attempt` };
  }
  return { dispatch: true, reason: `no check recorded for ${key} Pacific` };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      const now = new Date(event.scheduledTime);
      // Cheap check first, so most ticks cost no subrequests at all.
      if (!RUN_HOURS.includes(pacificHour(now))) return;
      const { dispatch: due, reason } = decide(now, await coverage());
      console.log(`${hourKey(now)} Pacific: ${due ? 'dispatching' : 'skipping'} — ${reason}`);
      if (due) await dispatch(env.GITHUB_TOKEN);
    })());
  },
};
