import test from 'node:test';
import assert from 'node:assert/strict';
import { sendAlert, configuredChannels } from '../notify.js';

const TWILIO = { TWILIO_ACCOUNT_SID: 'AC1', TWILIO_AUTH_TOKEN: 'tok', TWILIO_FROM: '+15550001111', ALERT_TO: '+15552223333' };
const PUSHOVER = { PUSHOVER_TOKEN: 'app', PUSHOVER_USER: 'usr' };
const alert = { title: 'Mixed Relay open', text: 'Friday: 1 left', url: 'https://shop.example/x', urgent: true };

function recorder(status = 200) {
  const calls = [];
  const fn = async (url, init) => { calls.push({ url, init, body: Object.fromEntries(init.body) }); return new Response('{}', { status }); };
  return { calls, fn };
}

test('no secrets, no channels', async () => {
  assert.deepEqual(configuredChannels({}), []);
  await assert.rejects(sendAlert({}, alert, recorder().fn), /No alert channel/);
});

test('Twilio sends an SMS with the shop link and basic auth', async () => {
  const { calls, fn } = recorder(201);
  await sendAlert(TWILIO, alert, fn);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json');
  assert.equal(calls[0].init.headers.authorization, `Basic ${btoa('AC1:tok')}`);
  assert.deepEqual(calls[0].body, { To: '+15552223333', From: '+15550001111', Body: 'Friday: 1 left\nhttps://shop.example/x' });
});

test('Twilio Messaging Service SID is sent as MessagingServiceSid', async () => {
  const { calls, fn } = recorder(201);
  await sendAlert({ ...TWILIO, TWILIO_FROM: 'MGabc' }, alert, fn);
  assert.equal(calls[0].body.MessagingServiceSid, 'MGabc');
  assert.equal(calls[0].body.From, undefined);
});

test('Pushover sends high priority with a link button', async () => {
  const { calls, fn } = recorder();
  await sendAlert(PUSHOVER, alert, fn);
  assert.equal(calls[0].url, 'https://api.pushover.net/1/messages.json');
  assert.equal(calls[0].body.priority, '1');
  assert.equal(calls[0].body.url, 'https://shop.example/x');
  const quiet = recorder();
  await sendAlert(PUSHOVER, { ...alert, urgent: false }, quiet.fn);
  assert.equal(quiet.calls[0].body.priority, '0');
});

test('both channels configured: one success is enough', async () => {
  const fn = async (url) => new Response('nope', { status: url.includes('twilio') ? 400 : 200 });
  const results = await sendAlert({ ...TWILIO, ...PUSHOVER }, alert, fn);
  assert.deepEqual(results.map((r) => [r.name, r.ok]), [['twilio', false], ['pushover', true]]);
});

test('every channel failing throws so the opening is retried', async () => {
  const fn = async () => new Response('down', { status: 500 });
  await assert.rejects(sendAlert({ ...TWILIO, ...PUSHOVER }, alert, fn), /Every alert channel failed/);
});
