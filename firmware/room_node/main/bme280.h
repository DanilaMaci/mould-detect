#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"

// Add the BME280 (address 0x77) to the bus, check chip ID, read calibration, start measuring.
esp_err_t bme280_init(i2c_master_bus_handle_t bus);

// Read one compensated measurement.
esp_err_t bme280_read(float *temp_c, float *press_hpa, float *rh);
