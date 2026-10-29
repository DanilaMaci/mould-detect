#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "onewire.h"
#include "ds18b20.h"

static const char *TAG = "ds18b20";

#define FAMILY_DS18B20     0x28
// 1-Wire ROM commands, then DS18B20 function commands (DS18B20 datasheet)
#define CMD_SEARCH_ROM     0xF0
#define CMD_MATCH_ROM      0x55
#define CMD_SKIP_ROM       0xCC
#define CMD_CONVERT_T      0x44
#define CMD_READ_SCRATCH   0xBE
#define CONVERT_MS         750      // 12-bit resolution, the power-on default
#define RAW_POWER_ON       0x0550   // 85 °C: what the register holds before the first conversion
#define MAX_SEARCH_PASSES  16

// Dallas/Maxim CRC-8: polynomial x^8 + x^5 + x^4 + 1, processed LSB first (0x8C), start value 0
static uint8_t crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x01) ? (uint8_t)((crc >> 1) ^ 0x8C) : (uint8_t)(crc >> 1);
        }
    }
    return crc;
}

// 1-Wire sends every byte least significant bit first
static void write_byte(uint8_t b)
{
    for (int i = 0; i < 8; i++) ow_write_bit((b >> i) & 1);
}

static uint8_t read_byte(void)
{
    uint8_t b = 0;
    for (int i = 0; i < 8; i++) {
        if (ow_read_bit()) b |= (uint8_t)(1 << i);
    }
    return b;
}

// One pass of the ROM search (Maxim application note 187). Each probe answers every ROM bit with the bit
// and its complement; all probes talk at once, so a 0 from any of them wins. 0 + 0 means the probes
// disagree at that bit: the master picks a branch and the probes on the other branch drop out.
// `rom` holds the previous pass's result and receives the next ROM code. `last_conflict` is the bit (1-64)
// where the previous pass last took the 0 branch (0 before the first pass); on return it is the value for
// the next pass, and 0 means this was the last probe.
static esp_err_t search_next(uint8_t rom[8], int *last_conflict)
{
    esp_err_t err = ow_reset();
    if (err != ESP_OK) return err;
    write_byte(CMD_SEARCH_ROM);

    int last_zero = 0;
    for (int n = 1; n <= 64; n++) {
        uint8_t *byte = &rom[(n - 1) / 8];
        uint8_t mask = (uint8_t)(1 << ((n - 1) % 8));
        bool bit = ow_read_bit();
        bool complement = ow_read_bit();
        bool dir;

        if (bit && complement) {
            return ESP_ERR_NOT_FOUND;           // no probe answered this bit
        } else if (bit != complement) {
            dir = bit;                          // all remaining probes agree
        } else {
            // Conflict: below the previous turning point repeat the previous path, at it take the
            // 1 branch this time, above it start with the 0 branch
            if (n < *last_conflict) dir = (*byte & mask) != 0;
            else dir = (n == *last_conflict);
            if (!dir) last_zero = n;
        }
        if (dir) *byte |= mask;
        else *byte &= (uint8_t)~mask;
        ow_write_bit(dir);
    }

    if (crc8(rom, 7) != rom[7]) return ESP_ERR_INVALID_CRC;
    *last_conflict = last_zero;
    return ESP_OK;
}

int ds18b20_init(int gpio, uint8_t roms[][8], int max)
{
    if (ow_init(gpio) != ESP_OK) return 0;

    uint8_t rom[8] = {0};
    int last_conflict = 0;
    int found = 0;
    int passes = 0;
    do {
        // Each pass finds a different device; the cap keeps a noisy bus from looping forever at boot
        if (++passes > MAX_SEARCH_PASSES) break;
        esp_err_t err = search_next(rom, &last_conflict);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "search: %s (check wiring and the 4.7 kOhm pull-up)", esp_err_to_name(err));
            break;
        }
        ESP_LOGI(TAG, "ROM %02X%02X%02X%02X%02X%02X%02X%02X", rom[0], rom[1], rom[2], rom[3],
                 rom[4], rom[5], rom[6], rom[7]);
        if (rom[0] != FAMILY_DS18B20) {
            ESP_LOGW(TAG, "family 0x%02X is not a DS18B20, ignored", rom[0]);
            continue;
        }
        memcpy(roms[found++], rom, 8);
    } while (last_conflict != 0 && found < max);

    ESP_LOGI(TAG, "%d probe(s) found", found);
    return found;
}

esp_err_t ds18b20_convert_all(void)
{
    esp_err_t err = ow_reset();
    if (err != ESP_OK) return err;
    write_byte(CMD_SKIP_ROM);                   // address every probe at once
    write_byte(CMD_CONVERT_T);
    // +1 tick: rounding down could end the wait a little before the conversion has finished
    vTaskDelay(pdMS_TO_TICKS(CONVERT_MS) + 1);
    return ESP_OK;
}

esp_err_t ds18b20_read(const uint8_t rom[8], float *temp_c)
{
    esp_err_t err = ow_reset();
    if (err != ESP_OK) return err;
    write_byte(CMD_MATCH_ROM);                  // only the probe with this ROM code answers
    for (int i = 0; i < 8; i++) write_byte(rom[i]);
    write_byte(CMD_READ_SCRATCH);

    // Scratchpad: temperature LSB, MSB, alarm high, alarm low, configuration, 3 reserved, CRC
    uint8_t sp[9];
    for (int i = 0; i < 9; i++) sp[i] = read_byte();
    if (crc8(sp, 8) != sp[8]) return ESP_ERR_INVALID_CRC;

    int16_t raw = (int16_t)((sp[1] << 8) | sp[0]);   // two's complement, 1/16 °C per step
    if (raw == RAW_POWER_ON) return ESP_ERR_INVALID_STATE;
    *temp_c = raw / 16.0f;
    return ESP_OK;
}
