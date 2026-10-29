# Firmware

ESP-IDF v6.1 projects in C, one folder per node type. Build each from its own folder with `idf.py`.

| Project | Hardware | Status |
|---|---|---|
| `room_node/` | ESP32-DevKitC + BME280 + SCD-40 + DS18B20 probes + 2 buttons/LEDs | Sends temperature, humidity, pressure, CO2, wall and outdoor temperature, window/door state and Wi-Fi RSSI to Supabase every minute over HTTPS. Planned: hub for the XIAO nodes (ESP-NOW → Supabase) |
| `wall_node/` | XIAO ESP32C3 + reed switch | Not in the repo; on hold: the probes went onto `room_node`, which sits by the balcony wall |
| `window_node/` | XIAO ESP32C3 + reed switch, battery | Not in the repo yet. Planned: deep sleep, wakes on window change, ESP-NOW (Espressif's Wi-Fi-free radio link) to the hub |

Parts and the reasons for this split: [docs/hardware.md](../docs/hardware.md).

When a driver is needed by more than one node (BME280, Wi-Fi, HTTPS client), it moves into `components/` as an
ESP-IDF component shared by all projects.

## room_node

| Part | Connection |
|---|---|
| ESP32-DevKitC (ESP32-D0WD-V3, 4 MB flash) | USB serial / 5 V USB charger |
| BME280 breakout (I2C, address 0x77) | VIN → 3V3, GND → GND, SDI (SDA) → GPIO21, SCK (SCL) → GPIO22 |
| SCD-40 STEMMA QT breakout (I2C, address 0x62) | VIN → 3V3, GND → GND, SDA → GPIO21, SCL → GPIO22 (same bus), 3Vo unconnected |
| DS18B20 probes (1-Wire, all in parallel) | red (VDD) → 3V3, blue or black → GND, yellow or white (DATA) → GPIO4 (Adafruit-style 3-wire probe colours); **one** 4.7 kΩ resistor from GPIO4 to 3V3 for the whole bus. Check the colours on the product page: 3 wires = DS18B20, 2 wires = a thermistor (different driver) |
| Window and door buttons | window: GPIO25, door: GPIO26 (internal pull-up). One button side to GND, the other side to the GPIO, and nothing else may ground the GPIO side. On these 4-leg buttons the legs 2 holes apart are joined inside: with the button on the − rail, keep one rail leg in, bend the other rail leg out, and put the GPIO wire in the row of the leg across from the bent one. Check: plugging the GPIO wire in must not flip the LED |
| Window and door LEDs | window (red): GPIO27, door (yellow): GPIO32; each GPIO → 330 Ω → LED long leg, short leg → GND |

At boot the node scans the I2C bus and logs every address that answers. Each minute's row includes the SCD-40's
CO2, temperature and humidity (null if it had no new value). If the SCD-40 is missing, the BME280 logging carries on.
DS18B20 probes are searched once at boot (restart after plugging one in): each one's 64-bit ROM code is logged,
then every minute a line `probe <ROM>: <T> degC`. The probe whose ROM is `WALL_PROBE_ROM` in `main.c` is uploaded as
`wall_temp_c`, any other as `outdoor_temp_c`. A read of exactly 85 °C (the power-on value) or a CRC error is
logged as a failure and sent as null.

The buttons are a stopgap until magnetic contacts are fitted: press the window button when opening or closing a
window, the door button when closing or opening the room door. Each LED shows its state (lit = open). At boot the
windows count as closed and the door as open. Every row carries both states; a press also sends a row at once.

Apply the migrations up to `supabase/migrations/20261022040000_probes_and_manual_states.sql` before flashing this
version: rows with unknown columns are rejected.

### Host tests (no ESP-IDF needed)

```bash
firmware/room_node/test_host/run.sh    # SCD-40 and DS18B20 drivers: CRC, commands, conversion, error paths;
                                       # DS18B20 against a simulated 1-Wire bus with several probes (ROM search);
                                       # buttons: debounce, one toggle per press, LEDs, early upload
```

The ESP32 supports 2.4 GHz Wi-Fi only.

### Credentials

Copy the example files in `room_node/main/` and fill them in:

```bash
cd firmware/room_node/main
cp wifi_secrets.example.h wifi_secrets.h
cp supabase_secrets.example.h supabase_secrets.h   # publishable key only, never the secret key
```

`*secrets.h` is in `.gitignore`. The publishable key can only insert rows (see `supabase/migrations/`).

### Build, flash, monitor

```bash
get_idf                          # activate ESP-IDF in this terminal
cd firmware/room_node
idf.py build flash monitor       # Ctrl+] to exit the monitor
```

No `-p` needed: `idf.py` tries each serial port and uses the one where an ESP32 answers. With several boards
plugged in, pick one by its port name. On macOS the DevKitC's USB-serial chip appears as
`/dev/cu.usbserial-*`, `/dev/cu.SLAB_USBtoUART` or `/dev/cu.wchusbserial*`, and the XIAO ESP32C3's built-in USB as
`/dev/cu.usbmodem*`:

```bash
idf.py -p "$(ls /dev/cu.* | grep -E 'usbserial|SLAB|wchusbserial' | head -1)" flash monitor   # DevKitC
idf.py -p "$(ls /dev/cu.* | grep usbmodem | head -1)" flash monitor                           # XIAO
```

The number in `usbserial-1140` is the USB socket's location, so it changes when the board goes into another socket
or hub. (`ls | grep` instead of a glob: in zsh an unmatched glob aborts the whole command.)
