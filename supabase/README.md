# Database (Supabase Postgres)

The schema lives in `migrations/` as SQL files named `YYYYMMDDHHMMSS_description.sql`, applied in name order. This
is the layout the Supabase CLI uses (`supabase db push`); each file can also be pasted into the SQL Editor.

| Migration | What it does |
|---|---|
| `20261006000000_indoor_readings.sql` | `indoor_readings` table with range checks; the publishable key may only insert (GRANT + RLS) |
| `20261022000000_scd40_columns.sql` | `co2_ppm`, `scd_temp_c`, `scd_rh` (nullable) with range checks |
| `20261022010000_weather_hourly.sql` | `weather_hourly`: Open-Meteo hourly weather, one row per hour; only the secret key can write |
| `20261022020000_service_role_grants.sql` | Table privileges for the secret key's role: upsert weather, read sensor data |
| `20261022030000_dashboard_read_access.sql` | Dashboard: read access for signed-in users in `dashboard_viewers`, `readings_hourly` view, Realtime |
| `20261022040000_probes_and_manual_states.sql` | `wall_temp_c`, `outdoor_temp_c` (DS18B20), `window_open`, `door_open` (buttons), all nullable |
| `20261022050000_hourly_view_probes_states.sql` | `readings_hourly` gains the probes and the fraction of each hour with a window open / the door open |

**Applying and tracking.** Migrations are applied by hand in the SQL Editor, in name order, so Supabase itself keeps
no record of which ones ran. Each new migration is listed in [CHANGELOG.md](../CHANGELOG.md) under the version that
needs it. To check that the latest one (`20261022050000`) is applied, run in the SQL Editor:

```sql
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'readings_hourly' order by ordinal_position;
```

The list must end with `wall_temp_c, outdoor_temp_c, window_open, door_open`. Later option: the Supabase CLI
(`supabase link`, then `supabase migration list` / `supabase db push`) records applied migrations in the database
itself.

Rules:

- Never edit a migration that has been applied; add a new one.
- New tables get no privileges automatically in this project: every new table needs explicit GRANTs for each
  role that uses it (service_role included, even though it bypasses RLS).
- Devices use the publishable key with insert-only access. The secret key is only used by server-side jobs and
  never appears in firmware or in this repository.
