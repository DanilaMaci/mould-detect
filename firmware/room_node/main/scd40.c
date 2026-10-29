#include <stdint.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "scd40.h"

static const char *TAG = "scd40";

#define SCD40_ADDR  0x62

// 16-bit commands from the SCD4x datasheet
#define CMD_START_PERIODIC    0x21B1
#define CMD_STOP_PERIODIC     0x3F86
#define CMD_READ_MEASUREMENT  0xEC05
#define CMD_DATA_READY        0xE4B8
#define CMD_SERIAL_NUMBER     0x3682

static i2c_master_dev_handle_t dev;

// Sensirion CRC-8 over one 2-byte word: polynomial 0x31, start value 0xFF
static uint8_t crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

static esp_err_t send_command(uint16_t cmd)
{
    uint8_t buf[2] = {cmd >> 8, cmd & 0xFF};
    return i2c_master_transmit(dev, buf, 2, 100);
}

// Send a command, wait while the sensor executes it, then read n words (2 data bytes + 1 CRC each)
static esp_err_t read_words(uint16_t cmd, uint32_t exec_ms, uint16_t *words, int n)
{
    uint8_t raw[9];
    if (n < 1 || n > 3) return ESP_ERR_INVALID_ARG;

    esp_err_t err = send_command(cmd);
    if (err != ESP_OK) return err;
    // +1 tick: at 100 Hz, pdMS_TO_TICKS(1) is 0, which would not wait at all
    vTaskDelay(pdMS_TO_TICKS(exec_ms) + 1);

    err = i2c_master_receive(dev, raw, n * 3, 100);
    if (err != ESP_OK) return err;

    for (int i = 0; i < n; i++) {
        const uint8_t *w = &raw[i * 3];
        if (crc8(w, 2) != w[2]) return ESP_ERR_INVALID_CRC;
        words[i] = (uint16_t)((w[0] << 8) | w[1]);
    }
    return ESP_OK;
}

esp_err_t scd40_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = SCD40_ADDR,
        .scl_speed_hz = 100000,                 // SCD4x maximum
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &dev_cfg, &dev);
    if (err != ESP_OK) return err;

    vTaskDelay(pdMS_TO_TICKS(1000));            // power-up time

    // The sensor keeps measuring across an ESP32 reset, and while measuring it ignores most
    // commands. Stop it first; this may fail harmlessly if it was already idle.
    send_command(CMD_STOP_PERIODIC);
    vTaskDelay(pdMS_TO_TICKS(500));

    uint16_t serial[3];
    err = read_words(CMD_SERIAL_NUMBER, 1, serial, 3);
    if (err != ESP_OK) return err;
    ESP_LOGI(TAG, "serial %04X%04X%04X", serial[0], serial[1], serial[2]);

    err = send_command(CMD_START_PERIODIC);
    if (err != ESP_OK) return err;
    ESP_LOGI(TAG, "measuring every 5 s");
    return ESP_OK;
}

esp_err_t scd40_read(uint16_t *co2_ppm, float *temp_c, float *rh)
{
    uint16_t status;
    esp_err_t err = read_words(CMD_DATA_READY, 1, &status, 1);
    if (err != ESP_OK) return err;
    if ((status & 0x07FF) == 0) return ESP_ERR_INVALID_STATE;   // lowest 11 bits 0: no new value

    uint16_t w[3];
    err = read_words(CMD_READ_MEASUREMENT, 1, w, 3);
    if (err != ESP_OK) return err;

    *co2_ppm = w[0];
    *temp_c  = -45.0f + 175.0f * w[1] / 65536.0f;
    *rh      = 100.0f * w[2] / 65536.0f;
    return ESP_OK;
}
