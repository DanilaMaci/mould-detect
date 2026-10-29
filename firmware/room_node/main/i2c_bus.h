#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"

// Create the shared I2C bus (SDA 21, SCL 22) used by all sensors on this node.
esp_err_t i2c_bus_init(i2c_master_bus_handle_t *bus);

// Log the address of every device that answers on the bus (wiring check at boot).
void i2c_bus_scan(i2c_master_bus_handle_t bus);
