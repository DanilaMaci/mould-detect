#pragma once
#include <stdint.h>
#include "esp_err.h"

// DS18B20 temperature probes on one 1-Wire bus. Each probe has a unique 64-bit ROM code
// (byte 0 = family 0x28, bytes 1-6 = serial, byte 7 = CRC), which tells the probes apart.

// Set up the bus on `gpio` and find up to `max` probes; their ROM codes go into `roms`.
// Returns the number found (0 if none or on a bus error).
int ds18b20_init(int gpio, uint8_t roms[][8], int max);

// Start a temperature conversion on every probe at once and wait for it (750 ms at 12 bit).
esp_err_t ds18b20_convert_all(void);

// Read one probe's last conversion. ESP_ERR_NOT_FOUND: no probe answered; ESP_ERR_INVALID_CRC:
// data corrupted on the wire; ESP_ERR_INVALID_STATE: power-on value 85 °C, so no conversion ran.
esp_err_t ds18b20_read(const uint8_t rom[8], float *temp_c);
