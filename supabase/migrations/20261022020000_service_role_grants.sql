-- Table privileges for the secret key's role (service_role), used only by the server-side jobs.
-- This project does not grant privileges on new tables to the API roles by default. service_role bypasses
-- RLS, but still needs table privileges: without them every request fails with 42501 "permission denied".

-- jobs/fetch_weather.py upserts: insert new hours, update existing ones
grant select, insert, update on table public.weather_hourly to service_role;

-- Analysis exports and scheduled risk jobs read the sensor data
grant select on table public.indoor_readings to service_role;
