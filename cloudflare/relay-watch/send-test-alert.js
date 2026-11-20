// Send one test alert through whichever channels have credentials in the
// environment, to confirm your phone receives it before relying on the Worker.
//
//   PUSHOVER_TOKEN=… PUSHOVER_USER=… node send-test-alert.js
//   TWILIO_ACCOUNT_SID=… TWILIO_AUTH_TOKEN=… TWILIO_FROM=… ALERT_TO=… node send-test-alert.js
import { sendAlert, configuredChannels } from './notify.js';

const channels = configuredChannels(process.env);
console.log(`Channels configured: ${channels.join(', ') || 'none'}`);
const results = await sendAlert(process.env, {
  title: 'HYROX relay watch: test alert',
  text: 'Test only. If this reached your phone, real Mixed Relay alerts will too.',
  url: 'https://usa.hyrox.com/tickets/6ae9ed7c0d921b7c5db5a99b',
  urgent: true,
});
for (const r of results) console.log(`${r.name}: ${r.ok ? 'sent' : `FAILED ${r.error}`}`);
