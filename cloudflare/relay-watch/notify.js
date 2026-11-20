/**
 * Alert channels. Each one is used only when its secrets are set, so the
 * Worker can start with whichever is ready (Pushover works immediately; US
 * SMS through Twilio needs a registered sending number) and add the other
 * later without a code change.
 *
 * Twilio:   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, ALERT_TO
 *           (TWILIO_FROM may be a phone number or a Messaging Service SID "MG…")
 * Pushover: PUSHOVER_TOKEN, PUSHOVER_USER
 */

const form = (fields) => new URLSearchParams(Object.entries(fields).filter(([, v]) => v !== undefined && v !== ''));

export const CHANNELS = {
  twilio: {
    configured: (env) => Boolean(env.TWILIO_ACCOUNT_SID && env.TWILIO_AUTH_TOKEN && env.TWILIO_FROM && env.ALERT_TO),
    async send(env, alert, fetchFn) {
      const from = env.TWILIO_FROM.startsWith('MG') ? { MessagingServiceSid: env.TWILIO_FROM } : { From: env.TWILIO_FROM };
      const body = alert.url ? `${alert.text}\n${alert.url}` : alert.text;
      return fetchFn(`https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Messages.json`, {
        method: 'POST',
        headers: { authorization: `Basic ${btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`)}` },
        body: form({ To: env.ALERT_TO, ...from, Body: body }),
      });
    },
  },
  pushover: {
    configured: (env) => Boolean(env.PUSHOVER_TOKEN && env.PUSHOVER_USER),
    async send(env, alert, fetchFn) {
      return fetchFn('https://api.pushover.net/1/messages.json', {
        method: 'POST',
        body: form({
          token: env.PUSHOVER_TOKEN,
          user: env.PUSHOVER_USER,
          title: alert.title,
          message: alert.text,
          url: alert.url,
          url_title: alert.url ? 'Open ticket shop' : undefined,
          // 1 = high priority: sounds even in quiet hours. Openings use it;
          // watcher-health notices go out at normal priority.
          priority: String(alert.urgent ? 1 : 0),
        }),
      });
    },
  },
};

export const configuredChannels = (env) => Object.keys(CHANNELS).filter((name) => CHANNELS[name].configured(env));

/**
 * Send `alert` ({title, text, url?, urgent?}) on every configured channel.
 * Resolves with per-channel results when at least one succeeded; throws when
 * none is configured or every one failed, so the caller can retry next tick.
 */
export async function sendAlert(env, alert, fetchFn = fetch) {
  const names = configuredChannels(env);
  if (!names.length) throw new Error('No alert channel configured (set Twilio or Pushover secrets)');
  const results = await Promise.all(names.map(async (name) => {
    try {
      const response = await CHANNELS[name].send(env, alert, fetchFn);
      if (!response.ok) return { name, ok: false, error: `${response.status} ${await response.text()}`.slice(0, 300) };
      return { name, ok: true };
    } catch (error) {
      return { name, ok: false, error: String(error) };
    }
  }));
  if (!results.some((r) => r.ok)) {
    throw new Error(`Every alert channel failed: ${results.map((r) => `${r.name}: ${r.error}`).join('; ')}`);
  }
  return results;
}
