# Changelog

Notable changes per version. Versions follow [semantic versioning](https://semver.org): 0.x while the system is
still taking shape; the minor number goes up for new features, the patch number for fixes. Each release is a git tag
`vX.Y.Z`. Database changes are listed with their migration file, because they must be applied by hand
(see [supabase/README.md](supabase/README.md)).

## [Unreleased]

- Weather workflow: `actions/checkout@v7` (runs on Node 24; v4 used the retired Node 20)

## [0.1.0] - 2026-10-29

First public version.

- Room node firmware (ESP-IDF, C): BME280, SCD-40 CO₂, two DS18B20 probes (wall, outdoor), window/door buttons with
  LEDs; one HTTPS POST to Supabase per minute; drivers tested on the host without hardware
- Database: readings, hourly weather and dashboard read access; migrations `20261006000000` to `20261022050000`
- Weather: Open-Meteo sync that fills missing hours, hourly on GitHub Actions and while `dashboard/serve.py` runs
- Dashboard: 3D room, charts, dew point, wall-surface humidity, ventilation advice, replay; demo mode with
  synthetic data for the public site
- Services: pipeline monitor with phone alerts, self-hosted API, Locust load test with results
