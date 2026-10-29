-- Hourly outdoor weather from Open-Meteo, written by jobs/fetch_weather.py.
-- One row per source and hour (UTC). Each fetch upserts: past hours are refined, future hours are the latest
-- forecast (observed_at > fetched_at). No location is stored.

create table public.weather_hourly (
    observed_at      timestamptz not null,          -- start of the hour, UTC
    source           text        not null default 'open-meteo',
    temp_c           real,                          -- 2 m air temperature
    rh               real,                          -- 2 m relative humidity, %
    dew_point_c      real,
    press_hpa        real,                          -- surface pressure (comparable with the BME280)
    precip_mm        real,                          -- preceding hour
    cloud_cover_pct  real,
    wind_speed_ms    real,                          -- 10 m
    wind_dir_deg     real,
    shortwave_wm2    real,                          -- solar radiation, warms outside walls
    weather_code     smallint,                      -- WMO code (clear, fog, rain, snow...), drives the dashboard sky
    is_day           boolean,
    fetched_at       timestamptz not null default now(),
    primary key (source, observed_at),
    constraint w_temp_c_range     check (temp_c between -60 and 60),
    constraint w_rh_range         check (rh between 0 and 100),
    constraint w_press_hpa_range  check (press_hpa between 300 and 1100),
    constraint w_precip_mm_range  check (precip_mm >= 0),
    constraint w_cloud_range      check (cloud_cover_pct between 0 and 100),
    constraint w_wind_speed_range check (wind_speed_ms >= 0),
    constraint w_wind_dir_range   check (wind_dir_deg between 0 and 360),
    constraint w_shortwave_range  check (shortwave_wm2 >= 0),
    constraint w_weather_code     check (weather_code between 0 and 99)
);

comment on table public.weather_hourly is 'Open-Meteo hourly weather at the house (location not stored)';

-- Only the server-side job (secret key, bypasses RLS) writes here. The publishable key gets nothing:
-- revoke any default grants, and RLS with no policies blocks rows for everyone else.
revoke all on table public.weather_hourly from anon, authenticated;
alter table public.weather_hourly enable row level security;
