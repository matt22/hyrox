import test from 'node:test';
import assert from 'node:assert/strict';
import { check, infoUrl } from '../worker.js';
import { sanDiego } from './fixture.js';

class MemoryKV {
  constructor(value) { this.value = value; this.puts = 0; }
  async get() { return this.value ?? null; }
  async put(_key, value) { this.value = value; this.puts += 1; }
  get state() { return JSON.parse(this.value); }
}

function env(extra = {}) {
  return {
    STATE: new MemoryKV(), EVENT_ID: 'evt', EVENT_NAME: 'HYROX San Diego', SHOP_URL: 'https://shop/evt',
    PUSHOVER_TOKEN: 'app', PUSHOVER_USER: 'usr', ...extra,
  };
}

/** fetch stub: Vivenu returns `payload` (or an error status); alert endpoints record and succeed. */
function world(payload, { vivenuStatus = 200, alertStatus = 200 } = {}) {
  const alerts = [];
  const fetchFn = async (url, init) => {
    if (url === infoUrl('evt')) return new Response(JSON.stringify(payload), { status: vivenuStatus });
    alerts.push(Object.fromEntries(init.body));
    return new Response('{}', { status: alertStatus });
  };
  return { alerts, fetchFn, set(p) { payload = p; }, fail(s) { vivenuStatus = s; } };
}

const t0 = new Date('2026-11-20T08:00:00Z');
const at = (min) => new Date(t0.getTime() + min * 60000);

test('sold out: no alert and no KV write', async () => {
  const e = env();
  const w = world(sanDiego());
  assert.equal(await check(e, { fetchFn: w.fetchFn, now: t0 }), 'Friday=0');
  assert.equal(w.alerts.length, 0);
  assert.equal(e.STATE.puts, 0);
});

test('opening alerts once, then re-arms after selling out', async () => {
  const e = env();
  const w = world(sanDiego({ friday: 1, members: 3 }));
  assert.match(await check(e, { fetchFn: w.fetchFn, now: t0 }), /ALERTED/);
  assert.equal(w.alerts.length, 1);
  assert.equal(w.alerts[0].priority, '1');
  assert.match(w.alerts[0].message, /Friday: 1 left/);
  assert.equal(w.alerts[0].url, 'https://shop/evt');
  assert.deepEqual(e.STATE.state.available, ['Friday']);

  await check(e, { fetchFn: w.fetchFn, now: at(1) });
  assert.equal(w.alerts.length, 1, 'still open: no repeat alert');

  w.set(sanDiego());
  await check(e, { fetchFn: w.fetchFn, now: at(2) });
  assert.deepEqual(e.STATE.state.available, []);

  w.set(sanDiego({ friday: 2, members: 6 }));
  await check(e, { fetchFn: w.fetchFn, now: at(3) });
  assert.equal(w.alerts.length, 2, 'reopened: alert again');
});

test('failed alert delivery leaves state alone so the next tick retries', async () => {
  const e = env();
  const w = world(sanDiego({ friday: 1 }), { alertStatus: 500 });
  await assert.rejects(check(e, { fetchFn: w.fetchFn, now: t0 }), /Every alert channel failed/);
  assert.equal(e.STATE.puts, 0);
});

test('Vivenu trouble: one health notice after 10 minutes, one recovery notice', async () => {
  const e = env();
  const w = world(sanDiego(), { vivenuStatus: 503 });
  assert.match(await check(e, { fetchFn: w.fetchFn, now: t0 }), /check failed: Vivenu responded 503/);
  await check(e, { fetchFn: w.fetchFn, now: at(5) });
  assert.equal(w.alerts.length, 0, 'short blips stay quiet');
  await check(e, { fetchFn: w.fetchFn, now: at(10) });
  assert.equal(w.alerts.length, 1);
  assert.match(w.alerts[0].title, /can't read tickets/);
  assert.equal(w.alerts[0].priority, '0');
  await check(e, { fetchFn: w.fetchFn, now: at(11) });
  assert.equal(w.alerts.length, 1, 'notified once');
  const writesWhileFailing = e.STATE.puts;
  assert.ok(writesWhileFailing <= 2);

  w.fail(200);
  await check(e, { fetchFn: w.fetchFn, now: at(12) });
  assert.equal(w.alerts.length, 2);
  assert.match(w.alerts[1].title, /back to normal/);
  assert.equal(e.STATE.state.failingSince, null);
});

test('a renamed ticket is a failure, not a sell-out', async () => {
  const e = env();
  const payload = sanDiego();
  payload.tickets = payload.tickets.filter((t) => !/MIXED RELAY/.test(t.name));
  const w = world(payload);
  assert.match(await check(e, { fetchFn: w.fetchFn, now: t0 }), /No active Mixed Relay ticket/);
});

test('stops after STOP_AFTER', async () => {
  const w = world(sanDiego({ friday: 1 }));
  assert.match(await check(env({ STOP_AFTER: '2026-11-19' }), { fetchFn: w.fetchFn, now: t0 }), /stopped/);
  assert.equal(w.alerts.length, 0);
});
