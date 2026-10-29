#pragma once
#include <stdint.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

// Add the SCD-40 (address 0x62) to the bus, read its serial number, start measuring every 5 s.
esp_err_t scd40_init(i2c_master_bus_handle_t bus);

// Read the latest measurement. Returns ESP_ERR_INVALID_STATE if no new value since the last read,
// ESP_ERR_INVALID_CRC if the data was corrupted on the wire.
esp_err_t scd40_read(uint16_t *co2_ppm, float *temp_c, float *rh);
