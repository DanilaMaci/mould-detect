-- SCD-40 on the room node: CO2 plus the sensor's own temperature and humidity.
-- Null in rows from before the sensor was fitted, or when it had no new value.
-- The existing insert grant and RLS policy cover the new columns.

alter table public.indoor_readings
    add column co2_ppm    integer,                 -- SCD-40 output range is 0-40000 ppm
    add column scd_temp_c real,
    add column scd_rh     real,
    add constraint co2_ppm_range    check (co2_ppm between 0 and 40000),
    add constraint scd_temp_c_range check (scd_temp_c between -10 and 60),   -- SCD-40 operating range
    add constraint scd_rh_range     check (scd_rh between 0 and 100);
