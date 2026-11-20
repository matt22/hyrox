/**
 * Every-minute watcher for HYROX Mixed Relay tickets.
 *
 * Separate from the monitor's dispatch Worker in ../ on purpose: that one
 * holds the monitor to eight browser checks a day; this one makes one plain
 * JSON request a minute to Vivenu's public event endpoint for a single event
 * and alerts when a Mixed Relay day becomes buyable. Nothing here touches the
 * GitHub workflow or the monitor's state files.
 *
 * State lives in one KV key and is written only when something changes (a
 * day opens or sells out, the check starts or stops failing), which keeps it
 * far inside the free plan's 1,000 KV writes a day.
 */
import { mixedRelayStatus, newOpenings, describe } from './availability.js';
import { sendAlert } from './notify.js';

const STATE_KEY = 'state';
// Tolerate a few minutes of Vivenu or network trouble before saying so.
const FAILURE_ALERT_AFTER_MS = 10 * 60 * 1000;
const FETCH_TIMEOUT_MS = 20 * 1000;

export const infoUrl = (eventId) => `https://vivenu.com/api/events/info/${eventId}`;

async function loadState(kv) {
  try {
    return { available: [], failingSince: null, failureNotified: false, ...JSON.parse((await kv.get(STATE_KEY)) || '{}') };
  } catch {
    return { available: [], failingSince: null, failureNotified: false };
  }
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

async function fetchEvent(env, fetchFn) {
  const response = await fetchFn(infoUrl(env.EVENT_ID), {
    headers: { accept: 'application/json', 'user-agent': 'hyrox-relay-watch (personal ticket alert, 1 req/min)' },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`Vivenu responded ${response.status}`);
  return response.json();
}

/**
 * One check. Returns a short summary for the log; exported for tests.
 * @param {object} env  Worker env: STATE (KV), EVENT_ID, EVENT_NAME, SHOP_URL, STOP_AFTER?, channel secrets.
 */
export async function check(env, { fetchFn = fetch, now = new Date() } = {}) {
  if (env.STOP_AFTER && now.toISOString().slice(0, 10) > env.STOP_AFTER) {
    return `stopped: past STOP_AFTER ${env.STOP_AFTER}`;
  }
  const previous = await loadState(env.STATE);
  const next = { ...previous };
  const event = env.EVENT_NAME || 'HYROX';
  let summary;

  let status;
  try {
    status = mixedRelayStatus(await fetchEvent(env, fetchFn));
  } catch (error) {
    next.failingSince = previous.failingSince || now.toISOString();
    summary = `check failed: ${error.message}`;
    const failingFor = now - new Date(next.failingSince);
    if (!previous.failureNotified && failingFor >= FAILURE_ALERT_AFTER_MS) {
      await sendAlert(env, {
        title: `${event}: relay watcher can't read tickets`,
        text: `No successful check for ${Math.round(failingFor / 60000)} min (${error.message}). Silence does not mean sold out until this clears.`,
        url: env.SHOP_URL,
        urgent: false,
      }, fetchFn);
      next.failureNotified = true;
    }
    if (!same(previous, next)) await env.STATE.put(STATE_KEY, JSON.stringify(next));
    return summary;
  }

  if (previous.failureNotified) {
    await sendAlert(env, { title: `${event}: relay watcher back to normal`, text: 'Checks are succeeding again.', urgent: false }, fetchFn)
      .catch((error) => console.log(`recovery notice failed: ${error.message}`));
  }
  next.failingSince = null;
  next.failureNotified = false;

  const openings = newOpenings(status, previous.available);
  if (openings.length) {
    // Throws if no channel delivers; state is then left unchanged so the
    // same opening is alerted again on the next tick.
    await sendAlert(env, {
      title: `${event}: Mixed Relay tickets OPEN`,
      text: `Mixed Relay available: ${openings.map(describe).join('; ')}. Have all 4 athletes' names and emails ready.`,
      url: env.SHOP_URL,
      urgent: true,
    }, fetchFn);
  }
  next.available = status.available;
  summary = status.days.map((d) => `${d.day}=${d.left}`).join(' ') + (openings.length ? ' ALERTED' : '');

  if (!same(previous, next)) await env.STATE.put(STATE_KEY, JSON.stringify(next));
  return summary;
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(check(env, { now: new Date(controller.scheduledTime) })
      .then((summary) => console.log(summary))
      .catch((error) => { console.log(`relay-watch error: ${error.message}`); throw error; }));
  },
};
