// Host test of the SCD-40 driver: CRC, command sequence, conversion, error paths.
// Run: test_host/run.sh
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "../main/scd40.c"   // includes the static functions (crc8)

static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

// Scripted fake device: records commands, replies with queued bytes
static uint16_t sent[16];
static int n_sent;
static uint8_t reply[64];
static size_t reply_len, reply_pos;
static int delayed_ticks;

void vTaskDelay(TickType_t ticks) { delayed_ticks += ticks; }

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus, const i2c_device_config_t *cfg,
                                    i2c_master_dev_handle_t *d)
{
    (void)bus;
    CHECK(cfg->device_address == 0x62);
    CHECK(cfg->scl_speed_hz <= 100000);
    *d = (i2c_master_dev_handle_t)1;
    return ESP_OK;
}

esp_err_t i2c_master_transmit(i2c_master_dev_handle_t d, const uint8_t *buf, size_t len, int t)
{
    (void)d; (void)t;
    CHECK(len == 2);
    sent[n_sent++] = (uint16_t)((buf[0] << 8) | buf[1]);
    return ESP_OK;
}

esp_err_t i2c_master_receive(i2c_master_dev_handle_t d, uint8_t *buf, size_t len, int t)
{
    (void)d; (void)t;
    if (reply_pos + len > reply_len) return ESP_FAIL;
    memcpy(buf, reply + reply_pos, len);
    reply_pos += len;
    return ESP_OK;
}

static void reset(void) { n_sent = 0; reply_len = reply_pos = 0; delayed_ticks = 0; }

// Queue one word as the sensor sends it: MSB, LSB, CRC
static void queue_word(uint16_t w, int corrupt_crc)
{
    uint8_t b[2] = {w >> 8, w & 0xFF};
    reply[reply_len++] = b[0];
    reply[reply_len++] = b[1];
    reply[reply_len++] = crc8(b, 2) ^ (corrupt_crc ? 0x01 : 0x00);
}

int main(void)
{
    // 1. CRC: example from the Sensirion datasheet, CRC(0xBEEF) = 0x92
    const uint8_t beef[2] = {0xBE, 0xEF};
    CHECK(crc8(beef, 2) == 0x92);

    // 2. Init: stop, read serial number, start periodic measurement, in that order
    reset();
    queue_word(0x1234, 0); queue_word(0x5678, 0); queue_word(0x9ABC, 0);
    CHECK(scd40_init((i2c_master_bus_handle_t)1) == ESP_OK);
    CHECK(n_sent == 3);
    CHECK(sent[0] == 0x3F86 && sent[1] == 0x3682 && sent[2] == 0x21B1);
    CHECK(delayed_ticks >= 150);   // >= 1.5 s for power-up and stop

    // 3. Read: data ready, then 500 ppm, raw T 0x6667, raw RH 0x5EB9
    reset();
    queue_word(0x8006, 0);
    queue_word(500, 0); queue_word(0x6667, 0); queue_word(0x5EB9, 0);
    uint16_t co2 = 0; float t = 0, rh = 0;
    CHECK(scd40_read(&co2, &t, &rh) == ESP_OK);
    CHECK(sent[0] == 0xE4B8 && sent[1] == 0xEC05);
    CHECK(co2 == 500);
    CHECK(fabsf(t - 25.0f) < 0.01f);    // -45 + 175 * 26215 / 65536 = 25.0006
    CHECK(fabsf(rh - 37.0f) < 0.01f);   // 100 * 24249 / 65536 = 37.0010

    // 4. Waits at least one tick between command and read (1 ms rounds to 0 ticks at 100 Hz)
    CHECK(delayed_ticks >= 2);

    // 5. No new value: lowest 11 bits of the status are 0 -> no read_measurement sent
    reset();
    queue_word(0x8000, 0);
    CHECK(scd40_read(&co2, &t, &rh) == ESP_ERR_INVALID_STATE);
    CHECK(n_sent == 1);

    // 6. Corrupted CO2 word is rejected
    reset();
    queue_word(0x8006, 0);
    queue_word(500, 1); queue_word(0x6667, 0); queue_word(0x5EB9, 0);
    CHECK(scd40_read(&co2, &t, &rh) == ESP_ERR_INVALID_CRC);

    // 7. Sensor not answering (no reply bytes) is an error, not a value
    reset();
    CHECK(scd40_read(&co2, &t, &rh) != ESP_OK);

    printf(failures ? "%d check(s) failed\n" : "OK: all SCD-40 host checks passed\n", failures);
    return failures != 0;
}
