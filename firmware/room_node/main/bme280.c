#include <inttypes.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "bme280.h"

static const char *TAG = "bme280";

#define BME280_ADDR  0x77

static i2c_master_dev_handle_t dev;

typedef struct {
    uint16_t T1; int16_t T2; int16_t T3;
    uint16_t P1; int16_t P2; int16_t P3; int16_t P4; int16_t P5;
    int16_t  P6; int16_t P7; int16_t P8; int16_t P9;
    uint8_t  H1; int16_t H2; uint8_t H3; int16_t H4; int16_t H5; int8_t H6;
} bme280_calib_t;

static bme280_calib_t cal;
static int32_t t_fine;

static esp_err_t read_calibration(void)
{
    uint8_t reg = 0x88;
    uint8_t c[26];
    esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, c, 26, 100);
    if (err != ESP_OK) return err;

    cal.T1 = (uint16_t)(c[1]  << 8 | c[0]);
    cal.T2 = (int16_t) (c[3]  << 8 | c[2]);
    cal.T3 = (int16_t) (c[5]  << 8 | c[4]);
    cal.P1 = (uint16_t)(c[7]  << 8 | c[6]);
    cal.P2 = (int16_t) (c[9]  << 8 | c[8]);
    cal.P3 = (int16_t) (c[11] << 8 | c[10]);
    cal.P4 = (int16_t) (c[13] << 8 | c[12]);
    cal.P5 = (int16_t) (c[15] << 8 | c[14]);
    cal.P6 = (int16_t) (c[17] << 8 | c[16]);
    cal.P7 = (int16_t) (c[19] << 8 | c[18]);
    cal.P8 = (int16_t) (c[21] << 8 | c[20]);
    cal.P9 = (int16_t) (c[23] << 8 | c[22]);
    cal.H1 = c[25];

    reg = 0xE1;
    uint8_t h[7];
    err = i2c_master_transmit_receive(dev, &reg, 1, h, 7, 100);
    if (err != ESP_OK) return err;

    cal.H2 = (int16_t)(h[1] << 8 | h[0]);
    cal.H3 = h[2];
    cal.H4 = (int16_t)(((int16_t)(int8_t)h[3]) * 16 | (h[4] & 0x0F));
    cal.H5 = (int16_t)(((int16_t)(int8_t)h[5]) * 16 | (h[4] >> 4));
    cal.H6 = (int8_t)h[6];
    return ESP_OK;
}

static int32_t compensate_T(int32_t adc_T)
{
    int32_t var1 = ((((adc_T >> 3) - ((int32_t)cal.T1 << 1))) * ((int32_t)cal.T2)) >> 11;
    int32_t var2 = (((((adc_T >> 4) - ((int32_t)cal.T1)) *
                      ((adc_T >> 4) - ((int32_t)cal.T1))) >> 12) * ((int32_t)cal.T3)) >> 14;
    t_fine = var1 + var2;
    return (t_fine * 5 + 128) >> 8;
}

static uint32_t compensate_P(int32_t adc_P)
{
    int64_t var1 = ((int64_t)t_fine) - 128000;
    int64_t var2 = var1 * var1 * (int64_t)cal.P6;
    var2 = var2 + ((var1 * (int64_t)cal.P5) << 17);
    var2 = var2 + (((int64_t)cal.P4) << 35);
    var1 = ((var1 * var1 * (int64_t)cal.P3) >> 8) + ((var1 * (int64_t)cal.P2) << 12);
    var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)cal.P1) >> 33;
    if (var1 == 0) {
        return 0;
    }
    int64_t p = 1048576 - adc_P;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = (((int64_t)cal.P9) * (p >> 13) * (p >> 13)) >> 25;
    var2 = (((int64_t)cal.P8) * p) >> 19;
    p = ((p + var1 + var2) >> 8) + (((int64_t)cal.P7) << 4);
    return (uint32_t)p;
}

static uint32_t compensate_H(int32_t adc_H)
{
    int32_t v = t_fine - ((int32_t)76800);
    v = (((((adc_H << 14) - (((int32_t)cal.H4) << 20) - (((int32_t)cal.H5) * v)) +
           ((int32_t)16384)) >> 15) *
         (((((((v * ((int32_t)cal.H6)) >> 10) *
              (((v * ((int32_t)cal.H3)) >> 11) + ((int32_t)32768))) >> 10) +
            ((int32_t)2097152)) * ((int32_t)cal.H2) + 8192) >> 14));
    v = (v - (((((v >> 15) * (v >> 15)) >> 7) * ((int32_t)cal.H1)) >> 4));
    v = (v < 0 ? 0 : v);
    v = (v > 419430400 ? 419430400 : v);
    return (uint32_t)(v >> 12);
}

esp_err_t bme280_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BME280_ADDR,
        .scl_speed_hz = 100000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &dev_cfg, &dev);
    if (err != ESP_OK) return err;

    uint8_t reg = 0xD0;
    uint8_t chip_id = 0;
    err = i2c_master_transmit_receive(dev, &reg, 1, &chip_id, 1, 100);
    if (err != ESP_OK) return err;
    if (chip_id != 0x60) {
        ESP_LOGE(TAG, "unexpected chip id 0x%02X (BME280 is 0x60)", chip_id);
        return ESP_ERR_NOT_FOUND;
    }

    err = read_calibration();
    if (err != ESP_OK) return err;

    uint8_t ctrl_hum[2]  = {0xF2, 0x01};   // humidity x1
    err = i2c_master_transmit(dev, ctrl_hum, 2, 100);
    if (err != ESP_OK) return err;

    uint8_t ctrl_meas[2] = {0xF4, 0x27};   // temp x1, press x1, normal mode
    err = i2c_master_transmit(dev, ctrl_meas, 2, 100);
    if (err != ESP_OK) return err;

    vTaskDelay(pdMS_TO_TICKS(100));
    ESP_LOGI(TAG, "ready (chip id 0x60)");
    return ESP_OK;
}

esp_err_t bme280_read(float *temp_c, float *press_hpa, float *rh)
{
    uint8_t reg = 0xF7;
    uint8_t raw[8] = {0};
    esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, raw, 8, 100);
    if (err != ESP_OK) return err;

    int32_t adc_p = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) | (raw[2] >> 4);
    int32_t adc_t = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
    int32_t adc_h = ((int32_t)raw[6] << 8)  |  raw[7];

    int32_t  t = compensate_T(adc_t);   // first: sets t_fine
    uint32_t p = compensate_P(adc_p);
    uint32_t h = compensate_H(adc_h);

    *temp_c    = t / 100.0f;
    *press_hpa = p / 25600.0f;
    *rh        = h / 1024.0f;
    return ESP_OK;
}
