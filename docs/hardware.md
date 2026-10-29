# Hardware

Bought from DigiKey. Cite datasheet sections for accuracy figures (for example "SCD4x datasheet §1.1"); the PDFs
stay in the local, uncommitted `datasheets/` folder. Values marked [verify] are from memory and must be checked
against the datasheet before they appear in results.

## Parts

| Part | Model | Qty | Interface | Accuracy | Notes |
|---|---|---|---|---|---|
| Main board | Espressif ESP32-DevKitC (ESP32-D0WD-V3, 4 MB flash) | 1 | Wi-Fi 2.4 GHz, ESP-NOW | — | in use as room node; USB powered |
| Small boards | Seeed Studio XIAO ESP32C3 | 3 | Wi-Fi 2.4 GHz, BLE 5, ESP-NOW | — | single-core RISC-V; LiPo charger on board; DigiKey part no. ? |
| Temp/RH/pressure | Bosch BME280 breakout, I2C 0x77 | 1 | I2C | ±3 %RH, ±1 °C [verify] | in use since 2026-10-06 |
| CO2 + temp + RH | Sensirion SCD-40 on a STEMMA QT breakout | 1 | I2C, address 0x62 [verify] | ±(50 ppm + 5 % of reading), 400–2000 ppm [verify] | photoacoustic NDIR: measures real CO2; DigiKey part no. ? |
| Temperature probe, lead wire, −55…125 °C | likely DS18B20 in a waterproof sleeve [verify: part no.] | 2 | 1-Wire, needs a 4.7 kΩ pull-up | ±0.5 °C from −10 to 85 °C [verify] | on the room node, GPIO4 (wiring in `firmware/README.md`); one on the wall, one outdoors |
| Window sensor | not bought yet; suggested: wired surface-mount magnetic contact ("MC-38" type, reed switch + magnet in two housings) | 3–5 | GPIO, internal pull-up | — | French-door right leaf (+ left leaf if it opens), both side-panel windows, rug window if it opens; wired to the room node |
| Power | ? | | | | USB chargers; LiPo cells for battery nodes ? |

The SCD-40 also reports temperature and humidity, a second indoor reading next to the BME280. It
self-calibrates against fresh air (about 400 ppm), so the room needs regular airing for the calibration to stay right.

## Proposed node allocation

| Node | Board | Sensors | Power | Sends via |
|---|---|---|---|---|
| `room_node` (hub) | ESP32-DevKitC | BME280 + SCD-40 (same I2C bus: SDA GPIO21, SCL GPIO22; SCD-40 VIN → 3V3, GND → GND, 3Vo unconnected) | USB | Wi-Fi → Supabase; also receives ESP-NOW from the XIAOs |
| `wall_node` | on hold (2026-10-22): the room node sits at the desk by the balcony wall, so the probes and the balcony-screen contacts wire straight to it | — | — | — |
| `window_node` | XIAO ESP32C3 #2, #3 | reed switch each | LiPo, deep sleep | ESP-NOW → hub |

Why this split: the probes' lead wires reach both the cold wall and the balcony from one spot. The hub saves a fourth
board as gateway. The XIAOs only wake when something happens, which keeps battery nodes viable. ESP-NOW and Wi-Fi share
one radio, so the hub's ESP-NOW channel is the router's Wi-Fi channel.

On the ESP32-C3, only GPIO0–GPIO5 can wake the chip from deep sleep [verify], so the reed switch goes on one of
those pins. Avoid the strapping pins (GPIO2, GPIO8, GPIO9).

**Outdoor humidity:** from the Open-Meteo API, fetched by the Python job (not by the ESP32): no outdoor humidity sensor is owned, it is free and keyless, it also gives forecasts and an archive for backfilling, and fetching on the server avoids extra TLS work and a firmware change on the node.

## Planned: window contacts on the room node

All openings are on the balcony wall next to the desk, so each contact gets two wires to the room node: one to a GPIO
with the internal pull-up, one to GND. Closed window = magnet at the switch = contact closed = pin reads 0. Proposed
pins: GPIO25, 26, 27, 32, 33 (avoiding strapping pins 0/2/5/12/15, input-only 34–39 which have no pull-up, and the
pins already used: 4, 21, 22, 23) [checked against ESP32 pin rules from memory; verify on the DevKitC pinout].
Switch on the fixed frame, magnet on the moving part, gap ≤ ~10 mm when closed (check the product's rating). On the
side windows, mount at the top corner on the handle side, so both opening modes (if they also tilt) move the magnet away.

## Planned: advice LED

LED + 330 Ω on GPIO23 of the room node (the stage-1 blink wiring), lit when airing is advised. Already shown in
the dashboard's 3D model; the firmware and the way the node gets the advice are open (see `docs/roadmap.md`).

## Which temperature is which

Four sensors read temperature, but only two measure the same thing:

| Sensor | Measures | Used for |
|---|---|---|
| BME280, SCD-40 | room air (two readings of the same air) | room T for dew point, always paired with the RH from the **same** sensor (RH is relative to that sensor's own temperature) |
| DS18B20 wall | inside surface of the balcony wall | surface RH, mould risk (the ML target) |
| DS18B20 outdoor | outdoor air on the balcony | fRsi and features; cross-checked against Open-Meteo |

Side-by-side check before mounting: all four sensors together on the desk, away from the ESP32 board, for an hour.
The ice-bath-checked DS18B20s are the reference; the BME280/SCD-40 offset seen there is corrected in analysis.

## Placement

| Sensor | Location | Why |
|---|---|---|
| Wall probe | coldest spot of the balcony wall, found with the probe itself: tape it to each candidate (lower corner by the fireplace wall, wall–ceiling and wall–floor junctions, the French-door reveal, behind the hanging rug) for 15 min each on a cold evening and keep the coldest. Generally: coldest spot of an outside wall (corner, window reveal, behind furniture); tip flat on the wall with a dab of thermal paste, sleeve and first cm of lead held flat with thin tape | mould starts at the coldest surface; good contact so the tip reads the wall, not room air; no thick insulation over it, which would make that spot colder than the rest of the wall |
| Outdoor probe | balcony, in air ≥ 10 cm from wall and frame, inside a white radiation shield (stacked plant saucers or a white cup with holes, open at the bottom); cable in through the hinge side of the right-hand side window (chosen 2026-10-22; the hinge side is squeezed least), not the closing gap of a window in use | sun on the bare steel tip and the warm wall/frame bias the reading; the window gap leaks warm room air and gets crushed by the seal |
| SCD-40 | room height, away from windows, doors and where people breathe on it | CO2 near a person's face reads far above the room average |
| BME280 | away from the boards' own heat and sunlight | self-heating raises T and lowers RH |
