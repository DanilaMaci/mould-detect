#include "driver/i2c_master.h"
#include "esp_log.h"
#include "i2c_bus.h"

static const char *TAG = "i2c";

#define I2C_SDA  GPIO_NUM_21
#define I2C_SCL  GPIO_NUM_22

esp_err_t i2c_bus_init(i2c_master_bus_handle_t *bus)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_SDA,
        .scl_io_num = I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,   // the breakouts also have their own pull-ups
    };
    return i2c_new_master_bus(&bus_cfg, bus);
}

void i2c_bus_scan(i2c_master_bus_handle_t bus)
{
    int found = 0;
    for (uint16_t addr = 0x08; addr < 0x78; addr++) {
        if (i2c_master_probe(bus, addr, 50) == ESP_OK) {
            ESP_LOGI(TAG, "device at 0x%02X", addr);
            found++;
        }
    }
    ESP_LOGI(TAG, "scan: %d device(s), expected 0x62 (SCD-40) and 0x77 (BME280)", found);
}
