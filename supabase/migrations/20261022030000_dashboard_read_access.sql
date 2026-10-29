-- Read access for the dashboard: only signed-in users listed in dashboard_viewers can read sensor and weather
-- data. Signing up alone gives nothing. The device key (anon) stays insert-only.
--
-- After applying: create your user (Authentication -> Users -> Add user), then in the SQL Editor:
--   insert into public.dashboard_viewers (user_id) select id from auth.users where email = '<your email>';

create table public.dashboard_viewers (
    user_id   uuid primary key references auth.users (id) on delete cascade,
    added_at  timestamptz not null default now()
);
comment on table public.dashboard_viewers is 'Users allowed to read the dashboard data';
alter table public.dashboard_viewers enable row level security;
revoke all on table public.dashboard_viewers from anon, authenticated;

-- Policies call this instead of reading dashboard_viewers directly (viewers cannot read that table themselves)
create function public.is_dashboard_viewer()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (select 1 from public.dashboard_viewers where user_id = auth.uid());
$$;
revoke execute on function public.is_dashboard_viewer() from public, anon;
grant execute on function public.is_dashboard_viewer() to authenticated;

-- Sensor readings
grant select on table public.indoor_readings to authenticated;
create policy "dashboard viewers can read readings"
    on public.indoor_readings for select to authenticated
    using ((select public.is_dashboard_viewer()));

-- Weather
grant select on table public.weather_hourly to authenticated;
create policy "dashboard viewers can read weather"
    on public.weather_hourly for select to authenticated
    using ((select public.is_dashboard_viewer()));

-- Hourly averages for long time ranges (a week of minute rows is ~10 000 rows; this is ~170).
-- security_invoker: the view applies the caller's RLS, so it is as private as the table.
create view public.readings_hourly
with (security_invoker = true)
as
select
    date_trunc('hour', measured_at) as hour,
    device_id,
    avg(temp_c)::real     as temp_c,
    avg(rh)::real         as rh,
    avg(press_hpa)::real  as press_hpa,
    avg(co2_ppm)::real    as co2_ppm,
    avg(scd_temp_c)::real as scd_temp_c,
    avg(scd_rh)::real     as scd_rh,
    count(*)              as samples
from public.indoor_readings
group by 1, 2;
revoke all on table public.readings_hourly from anon;
grant select on table public.readings_hourly to authenticated;

-- Push new readings to the dashboard as they arrive (Realtime applies the same RLS policies)
alter publication supabase_realtime add table public.indoor_readings;
