import test from 'node:test';
import assert from 'node:assert/strict';
import { mixedRelayStatus, newOpenings, describe, StructureError } from '../availability.js';
import { sanDiego, RELAY } from './fixture.js';

test('sold out today: active ticket with v = 0 is not available', () => {
  const status = mixedRelayStatus(sanDiego());
  assert.deepEqual(status.available, []);
  assert.equal(status.days.length, 1);
  assert.equal(status.days[0].day, 'Friday');
  assert.equal(status.days[0].left, 0);
});

test('a returned ticket makes Friday available', () => {
  const status = mixedRelayStatus(sanDiego({ friday: 1, members: 3 }));
  assert.deepEqual(status.available, ['Friday']);
  assert.equal(status.days[0].membersLeft, 3);
});

test('category cap wins over ticket volume', () => {
  assert.deepEqual(mixedRelayStatus(sanDiego({ friday: 5, relayCategory: 0 })).available, []);
  assert.equal(mixedRelayStatus(sanDiego({ friday: 5, relayCategory: 2 })).days[0].left, 2);
});

test('other relay divisions and team-member tickets do not count', () => {
  const status = mixedRelayStatus(sanDiego({ members: 40 }));
  assert.deepEqual(status.available, []);
  assert.deepEqual(status.days.map((d) => d.day), ['Friday']);
});

test('a newly listed day is picked up', () => {
  const saturday = { _id: 'sat', name: 'HYROX MIXED RELAY | Saturday', active: true, v: 2, categoryRef: RELAY };
  const status = mixedRelayStatus(sanDiego({ extra: [saturday] }));
  assert.deepEqual(status.available, ['Saturday']);
  assert.equal(status.days.find((d) => d.day === 'Saturday').membersLeft, null);
});

test('inactive tickets are ignored', () => {
  const sunday = { _id: 'sun', name: 'HYROX MIXED RELAY | Sunday', active: false, v: 9, categoryRef: RELAY };
  assert.deepEqual(mixedRelayStatus(sanDiego({ extra: [sunday] })).available, []);
});

test('structure changes fail loudly instead of reading as sold out', () => {
  assert.throws(() => mixedRelayStatus({}), StructureError);
  const renamed = sanDiego();
  renamed.tickets = renamed.tickets.filter((t) => !/MIXED RELAY/.test(t.name));
  assert.throws(() => mixedRelayStatus(renamed), StructureError);
  const noVolume = sanDiego();
  for (const t of noVolume.tickets) delete t.v;
  noVolume.categories = [];
  assert.throws(() => mixedRelayStatus(noVolume), StructureError);
});

test('newOpenings reports only days that just opened', () => {
  const status = mixedRelayStatus(sanDiego({ friday: 1, members: 3 }));
  assert.deepEqual(newOpenings(status, []).map((d) => d.day), ['Friday']);
  assert.deepEqual(newOpenings(status, ['Friday']), []);
});

test('describe flags a team that will not fit', () => {
  const [full] = mixedRelayStatus(sanDiego({ friday: 2, members: 6 })).days;
  assert.equal(describe(full), 'Friday: 2 left');
  const [short] = mixedRelayStatus(sanDiego({ friday: 1, members: 1 })).days;
  assert.equal(describe(short), 'Friday: 1 left (only 1 team-member spot left)');
});

test('renamed ticket is still found by its RELAY_X key', () => {
  const payload = sanDiego({ friday: 3, members: 9 });
  payload.tickets[2].name = 'HYROX RELAY MIXED (OPEN) | Friday';
  payload.tickets[3].name = 'HYROX RELAY MIXED (OPEN) MEMBER | Friday';
  const status = mixedRelayStatus(payload);
  assert.deepEqual(status.available, ['Friday']);
  assert.equal(status.days[0].membersLeft, 9);
});

test('ticket with the key dropped is still found by name', () => {
  const payload = sanDiego({ friday: 1 });
  for (const t of payload.tickets) delete t.meta;
  assert.deepEqual(mixedRelayStatus(payload).available, ['Friday']);
});

test('charity, pro and adaptive variants never count', () => {
  const extra = [
    { _id: 'c', name: 'CHARITY: RACE FOR IMPACT | HYROX MIXED RELAY | Saturday', active: true, v: 9, categoryRef: RELAY },
    { _id: 'p', name: 'HYROX PRO MIXED RELAY | Saturday', active: true, v: 9, categoryRef: RELAY, meta: { competition_class_matching_key: 'RELAY_X' } },
  ];
  assert.deepEqual(mixedRelayStatus(sanDiego({ extra })).available, []);
});
