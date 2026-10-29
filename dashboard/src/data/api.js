// Live data source: the own API (services/api) instead of Supabase. Same interface as supabase.js, so the 3D room
// and charts run unchanged on either backend. Reads need the API's read token (API_READ_TOKEN in config.js): fine on
// this Mac, but a token in a page is visible to anyone who can open the page, so a public site would need a login.
// There is no push channel: new rows are fetched every pollMs (polling instead of Supabase Realtime).

const LIMIT = 5000;   // the API's maximum rows per request

export function createApiSource({ baseUrl, readToken, deviceId, pollMs = 15_000, fetchFn = fetch }) {
  const base = baseUrl.replace(/\/$/, '');

  async function get(path, params) {
    const res = await fetchFn(`${base}${path}?${new URLSearchParams(params)}`, {
      headers: { Authorization: `Bearer ${readToken}` },
      cache: 'no-store',
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(`API ${res.status}: ${body.error ?? res.statusText}`);
    }
    return res.json();
  }

  const toReading = ({ measured_at, hour, device_id, samples, ...rest }) => ({ t: Date.parse(measured_at ?? hour), ...rest });
  const toWeather = ({ observed_at, ...rest }) => ({ t: Date.parse(observed_at), ...rest });

  async function readings(fromMs, { hourly = false } = {}) {
    const params = { device_id: deviceId, since: new Date(fromMs).toISOString(),
      until: new Date(Date.now() + 60_000).toISOString(), limit: LIMIT };
    if (hourly) params.hourly = '1';
    return (await get('/api/readings', params)).map(toReading);
  }

  return {
    kind: 'live',
    async needsLogin() { return false; },
    async signIn() {},
    async signOut() {},
    readings,

    async weather(fromMs, toMs) {
      const rows = await get('/api/weather', { since: new Date(fromMs).toISOString(),
        until: new Date(toMs).toISOString(), limit: LIMIT });
      return rows.map(toWeather);
    },

    /** Polls for rows newer than the last one seen; onStatus gets 'SUBSCRIBED' after a good poll, else
     * 'CHANNEL_ERROR' (main.js then shows "polling" and adds its own slower poll). */
    subscribe(onReading, onStatus) {
      let last = Date.now();
      let ok = null;
      const poll = async () => {
        try {
          const rows = (await readings(last + 1)).filter((r) => r.t > last);
          for (const r of rows) onReading(r);
          if (rows.length) last = rows[rows.length - 1].t;
          if (ok !== true) onStatus?.('SUBSCRIBED');
          ok = true;
        } catch {
          if (ok !== false) onStatus?.('CHANNEL_ERROR');
          ok = false;
        }
      };
      poll();
      const timer = setInterval(poll, pollMs);
      return () => clearInterval(timer);
    },
  };
}
