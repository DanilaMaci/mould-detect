-- Room node v1.2: DS18B20 probes (wall surface, outdoor air) and the two manual toggle buttons.
-- Probe columns are null when a probe is missing or its read failed. window_open (any window) / door_open (room door)
-- come from buttons people press when they open or close them, shown on LEDs (lit = open); a stopgap until magnetic
-- contacts are fitted. At node boot: windows closed, door open. Null in rows from before the buttons existed.
-- Each press also sends an extra row at once, so state changes are timed to seconds.
-- The existing insert grant and RLS policy cover the new columns.

alter table public.indoor_readings
    add column wall_temp_c    real,
    add column outdoor_temp_c real,
    add column window_open    boolean,
    add column door_open      boolean,
    add constraint wall_temp_c_range    check (wall_temp_c between -55 and 125),      -- DS18B20 range
    add constraint outdoor_temp_c_range check (outdoor_temp_c between -55 and 125);
