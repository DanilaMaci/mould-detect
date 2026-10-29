// Live data source: Supabase with email/password login. Reads are allowed only for signed-in users listed in
// public.dashboard_viewers (see supabase/migrations/20261022030000_dashboard_read_access.sql).
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm';

const PAGE = 1000;   // Supabase's default maximum rows per request

const READING_COLUMNS = 'measured_at,temp_c,rh,press_hpa,co2_ppm,scd_temp_c,scd_rh,wall_temp_c,outdoor_temp_c,' +
  'window_open,door_open';
// Hourly view: same names; window_open / door_open are the fraction of the hour in that state (0..1)
const HOURLY_COLUMNS = 'hour,temp_c,rh,press_hpa,co2_ppm,scd_temp_c,scd_rh,wall_temp_c,outdoor_temp_c,window_open,door_open';
const WEATHER_COLUMNS = 'observed_at,temp_c,rh,dew_point_c,press_hpa,precip_mm,cloud_cover_pct,wind_speed_ms,' +
  'wind_dir_deg,shortwave_wm2,weather_code,is_day';

const toReading = ({ measured_at, hour, ...rest }) => ({ t: Date.parse(measured_at ?? hour), ...rest });
const toWeather = ({ observed_at, ...rest }) => ({ t: Date.parse(observed_at), ...rest });

async function fetchAll(makeQuery) {
  const rows = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await makeQuery().range(from, from + PAGE - 1);
    if (error) throw error;
    rows.push(...data);
    if (data.length < PAGE) return rows;
  }
}

export function createSupabaseSource({ url, publishableKey, deviceId }) {
  const client = createClient(url, publishableKey);

  return {
    kind: 'live',

    async needsLogin() {
      const { data } = await client.auth.getSession();
      return !data.session;
    },

    async signIn(email, password) {
      const { error } = await client.auth.signInWithPassword({ email, password });
      if (error) throw error;
    },

    async signOut() {
      await client.auth.signOut();
    },

    /** Readings since fromMs; hourly averages (view readings_hourly) for long ranges. */
    async readings(fromMs, { hourly = false } = {}) {
      const since = new Date(fromMs).toISOString();
      const rows = hourly
        ? await fetchAll(() => client.from('readings_hourly')
          .select(HOURLY_COLUMNS)
          .eq('device_id', deviceId).gte('hour', since).order('hour'))
        : await fetchAll(() => client.from('indoor_readings')
          .select(READING_COLUMNS)
          .eq('device_id', deviceId).gte('measured_at', since).order('measured_at'));
      return rows.map(toReading);
    },

    async weather(fromMs, toMs) {
      const rows = await fetchAll(() => client.from('weather_hourly')
        .select(WEATHER_COLUMNS)
        .eq('source', 'open-meteo')
        .gte('observed_at', new Date(fromMs).toISOString())
        .lte('observed_at', new Date(toMs).toISOString())
        .order('observed_at'));
      return rows.map(toWeather);
    },

    /** New rows pushed by Supabase Realtime. onStatus gets 'SUBSCRIBED', 'CHANNEL_ERROR', 'TIMED_OUT', 'CLOSED'. */
    subscribe(onReading, onStatus) {
      const channel = client
        .channel('indoor_readings_inserts')
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'indoor_readings',
          filter: `device_id=eq.${deviceId}` }, (payload) => onReading(toReading(payload.new)))
        .subscribe((status) => onStatus?.(status));
      return () => client.removeChannel(channel);
    },
  };
}
