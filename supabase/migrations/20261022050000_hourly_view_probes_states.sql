-- Dashboard: readings_hourly gains the DS18B20 probes and the window/door button states.
-- window_open / door_open here are the fraction of the hour's rows with that state (0..1), not booleans:
-- window_open > 0 means a window was open at some point in that hour, door_open < 1 that the door was closed.
-- New columns go after the existing ones (CREATE OR REPLACE VIEW cannot reorder or drop columns); the view's
-- privileges are kept, security_invoker is restated.

create or replace view public.readings_hourly
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
    count(*)              as samples,
    avg(wall_temp_c)::real              as wall_temp_c,
    avg(outdoor_temp_c)::real           as outdoor_temp_c,
    avg(window_open::int)::real         as window_open,
    avg(door_open::int)::real           as door_open
from public.indoor_readings
group by 1, 2;
