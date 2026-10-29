#pragma once
// Host stand-in for the ESP-IDF I2C master driver: the test scripts the device's replies
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct i2c_bus *i2c_master_bus_handle_t;
typedef struct i2c_dev *i2c_master_dev_handle_t;
typedef enum { I2C_ADDR_BIT_LEN_7 } i2c_addr_bit_len_t;
typedef struct {
    i2c_addr_bit_len_t dev_addr_length;
    uint16_t device_address;
    uint32_t scl_speed_hz;
} i2c_device_config_t;
esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus, const i2c_device_config_t *cfg,
                                    i2c_master_dev_handle_t *dev);
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t dev, const uint8_t *buf, size_t len, int timeout_ms);
esp_err_t i2c_master_receive(i2c_master_dev_handle_t dev, uint8_t *buf, size_t len, int timeout_ms);
