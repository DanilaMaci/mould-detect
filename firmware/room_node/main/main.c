#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_err.h"
#include "i2c_bus.h"
#include "bme280.h"
#include "scd40.h"
#include "ds18b20.h"
#include "toggles.h"
#include "wifi.h"
#include "supabase_secrets.h"

static const char *TAG = "node";

// Two string literals side by side are joined by the compiler into one string
#define TABLE_URL         SUP_URL "/rest/v1/indoor_readings"
#define DEVICE_ID         "node1"
#define SEND_INTERVAL_MS  (60 * 1000)
#define NODE_STACK_BYTES  8192          // TLS handshake needs a bigger stack
#define ONEWIRE_GPIO      4             // DS18B20 data line, 4.7 kOhm pull-up to 3V3
#define MAX_PROBES        4

// The wall probe is identified by its ROM code (printed at boot); any other probe is the outdoor one
static const uint8_t WALL_PROBE_ROM[8] = {0x28, 0xB4, 0xA5, 0xAB, 0x10, 0x00, 0x00, 0x53};

static bool scd40_ok;
static bool toggles_ok;
static uint8_t probe_roms[MAX_PROBES][8];
static int n_probes;

// Latest SCD-40 measurement; valid is false if there was no new value this cycle
typedef struct {
    bool valid;
    uint16_t co2_ppm;
    float temp_c;
    float rh;
} scd_reading_t;

// DS18B20 temperatures of this cycle; valid is false if the probe is missing or its read failed
typedef struct {
    bool wall_valid, outdoor_valid;
    float wall_c, outdoor_c;
} probe_reading_t;

// A number with 2 decimals, or JSON null
static void json_number(char *buf, size_t size, bool valid, float value)
{
    if (valid) snprintf(buf, size, "%.2f", value);
    else snprintf(buf, size, "null");
}

static const char *json_toggle(toggle_id_t id)
{
    if (!toggles_ok) return "null";
    return toggles_get(id) ? "true" : "false";
}

static esp_err_t post_reading(float temp_c, float press_hpa, float rh, const scd_reading_t *scd,
                              const probe_reading_t *probes)
{
    // 1. Signal strength: a number, or JSON null if unavailable
    char rssi_str[8];
    int rssi;
    if (wifi_get_rssi(&rssi) == ESP_OK) {
        snprintf(rssi_str, sizeof(rssi_str), "%d", rssi);
    } else {
        strcpy(rssi_str, "null");
    }

    // 2. SCD-40 values, or JSON null for each if there was no new reading
    char co2_str[8] = "null", scd_t_str[12] = "null", scd_rh_str[12] = "null";
    if (scd->valid) {
        snprintf(co2_str, sizeof(co2_str), "%u", (unsigned)scd->co2_ppm);
        snprintf(scd_t_str, sizeof(scd_t_str), "%.2f", scd->temp_c);
        snprintf(scd_rh_str, sizeof(scd_rh_str), "%.2f", scd->rh);
    }

    // 3. Probe temperatures, or JSON null for a missing probe
    char wall_str[12], outdoor_str[12];
    json_number(wall_str, sizeof(wall_str), probes->wall_valid, probes->wall_c);
    json_number(outdoor_str, sizeof(outdoor_str), probes->outdoor_valid, probes->outdoor_c);

    // 4. Build the JSON. Keys must match the table's column names
    char body[384];
    int len = snprintf(body, sizeof(body),
                       "{\"device_id\":\"%s\",\"temp_c\":%.2f,\"rh\":%.2f,"
                       "\"press_hpa\":%.2f,\"rssi_dbm\":%s,"
                       "\"co2_ppm\":%s,\"scd_temp_c\":%s,\"scd_rh\":%s,"
                       "\"wall_temp_c\":%s,\"outdoor_temp_c\":%s,"
                       "\"window_open\":%s,\"door_open\":%s}",
                       DEVICE_ID, temp_c, rh, press_hpa, rssi_str,
                       co2_str, scd_t_str, scd_rh_str, wall_str, outdoor_str,
                       json_toggle(TOGGLE_WINDOW_OPEN), json_toggle(TOGGLE_DOOR_OPEN));
    if (len < 0 || len >= (int)sizeof(body)) {
        return ESP_ERR_INVALID_SIZE;
    }

    // 5. HTTPS request: the certificate bundle checks we're really talking to Supabase
    esp_http_client_config_t cfg = {
        .url = TABLE_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        return ESP_FAIL;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_header(client, "apikey", SUP_API_PUBLIC_KEY);
    esp_http_client_set_header(client, "Prefer", "return=minimal");
    // If your key starts with "eyJ" (older anon key), also uncomment:
    // esp_http_client_set_header(client, "Authorization", "Bearer " SUP_API_PUBLIC_KEY);
    esp_http_client_set_post_field(client, body, len);

    // 6. Send. Supabase answers 201 Created on success
    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        int status = esp_http_client_get_status_code(client);
        ESP_LOGI(TAG, "POST %s -> %d", body, status);
        if (status != 201) {
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGW(TAG, "POST failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    return err;
}

// Convert and read every probe; the one with WALL_PROBE_ROM is the wall, the first other one is outdoors
static void read_probes(probe_reading_t *out)
{
    if (n_probes == 0) return;
    esp_err_t err = ds18b20_convert_all();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "probe conversion failed: %s", esp_err_to_name(err));
        return;
    }
    for (int i = 0; i < n_probes; i++) {
        const uint8_t *r = probe_roms[i];
        float t;
        err = ds18b20_read(r, &t);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "probe %02X%02X%02X%02X%02X%02X%02X%02X: %.2f degC",
                     r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], t);
            if (memcmp(r, WALL_PROBE_ROM, 8) == 0) {
                out->wall_valid = true;
                out->wall_c = t;
            } else if (!out->outdoor_valid) {
                out->outdoor_valid = true;
                out->outdoor_c = t;
            }
        } else {
            ESP_LOGW(TAG, "probe %d read failed: %s", i, esp_err_to_name(err));
        }
    }
}

// Our own task with an 8 KB stack (app_main's is only ~3.5 KB)
static void node_task(void *arg)
{
    while (1) {
        float t, p, h;
        esp_err_t err = bme280_read(&t, &p, &h);

        scd_reading_t scd = {0};
        if (scd40_ok) {
            esp_err_t err2 = scd40_read(&scd.co2_ppm, &scd.temp_c, &scd.rh);
            scd.valid = (err2 == ESP_OK);
            if (err2 == ESP_OK) {
                ESP_LOGI(TAG, "SCD-40: %u ppm, %.2f degC, %.2f %%RH",
                         (unsigned)scd.co2_ppm, scd.temp_c, scd.rh);
            } else if (err2 == ESP_ERR_INVALID_STATE) {
                ESP_LOGI(TAG, "SCD-40: no new value yet (first one ~5 s after start)");
            } else {
                ESP_LOGW(TAG, "SCD-40 read failed: %s", esp_err_to_name(err2));
            }
        }

        probe_reading_t probes = {0};
        read_probes(&probes);

        if (err != ESP_OK) {
            ESP_LOGW(TAG, "sensor read failed: %s", esp_err_to_name(err));
        } else if (!wifi_wait_connected(pdMS_TO_TICKS(10000))) {
            ESP_LOGW(TAG, "no Wi-Fi, reading skipped: %.2f degC %.2f %%RH", t, h);
        } else {
            post_reading(t, p, h, &scd, &probes);
        }

        // Sleep until the next minute, or wake early when a button is pressed so the change is logged at once
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(SEND_INTERVAL_MS));
    }
}

void app_main(void)
{
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_bus_init(&bus));
    i2c_bus_scan(bus);
    ESP_ERROR_CHECK(bme280_init(bus));

    // A missing SCD-40 must not stop the BME280 logging
    esp_err_t err = scd40_init(bus);
    scd40_ok = (err == ESP_OK);
    if (!scd40_ok) {
        ESP_LOGW(TAG, "SCD-40 not available (%s): check wiring", esp_err_to_name(err));
    }

    // Probes are found once at boot: restart the node after plugging one in
    n_probes = ds18b20_init(ONEWIRE_GPIO, probe_roms, MAX_PROBES);
    if (n_probes == 0) {
        ESP_LOGW(TAG, "no DS18B20 probe on GPIO%d", ONEWIRE_GPIO);
    }
    wifi_start();
    TaskHandle_t node;
    xTaskCreate(node_task, "node", NODE_STACK_BYTES, NULL, 5, &node);

    // Window/door buttons: a failure here must not stop the sensor logging (states are sent as null)
    err = toggles_start(node);
    toggles_ok = (err == ESP_OK);
    if (!toggles_ok) {
        ESP_LOGW(TAG, "buttons not available: %s", esp_err_to_name(err));
    }
    // app_main returns here; node_task keeps running forever
}
