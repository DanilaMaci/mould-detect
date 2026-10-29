#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_err.h"
#include "wifi_secrets.h"
#include "wifi.h"

static const char *TAG = "wifi";

static EventGroupHandle_t wifi_events;
#define WIFI_CONNECTED_BIT    (1 << 0)
#define WIFI_DISCONNECTED_BIT (1 << 1)

#define BACKOFF_START_S 1
#define BACKOFF_MAX_S   60

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "connecting to %s", WIFI_SSID);
        esp_wifi_connect();

    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d = (wifi_event_sta_disconnected_t *)data;
        ESP_LOGW(TAG, "disconnected (reason %d)", d->reason);
        xEventGroupClearBits(wifi_events, WIFI_CONNECTED_BIT);
        xEventGroupSetBits(wifi_events, WIFI_DISCONNECTED_BIT);

    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got IP " IPSTR, IP2STR(&e->ip_info.ip));
        xEventGroupSetBits(wifi_events, WIFI_CONNECTED_BIT);
    }
}

static void wifi_reconnect_task(void *arg)
{
    uint32_t delay_s = BACKOFF_START_S;

    while (1) {
        EventBits_t bits = xEventGroupWaitBits(wifi_events,
                                               WIFI_CONNECTED_BIT | WIFI_DISCONNECTED_BIT,
                                               pdFALSE, pdFALSE, portMAX_DELAY);
        if (bits & WIFI_CONNECTED_BIT) {
            delay_s = BACKOFF_START_S;
            xEventGroupWaitBits(wifi_events, WIFI_DISCONNECTED_BIT,
                                pdFALSE, pdTRUE, portMAX_DELAY);
        }

        xEventGroupClearBits(wifi_events, WIFI_DISCONNECTED_BIT);
        ESP_LOGW(TAG, "retrying in %" PRIu32 " s", delay_s);
        vTaskDelay(pdMS_TO_TICKS(delay_s * 1000));
        esp_wifi_connect();

        delay_s *= 2;
        if (delay_s > BACKOFF_MAX_S) {
            delay_s = BACKOFF_MAX_S;
        }
    }
}

void wifi_start(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));

    xTaskCreate(wifi_reconnect_task, "wifi_reconnect", 3072, NULL, 5, NULL);

    wifi_config_t wifi_cfg = {0};
    strncpy((char *)wifi_cfg.sta.ssid, WIFI_SSID, sizeof(wifi_cfg.sta.ssid));
    strncpy((char *)wifi_cfg.sta.password, WIFI_PASS, sizeof(wifi_cfg.sta.password));
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}

bool wifi_wait_connected(TickType_t timeout)
{
    EventBits_t bits = xEventGroupWaitBits(wifi_events, WIFI_CONNECTED_BIT,
                                           pdFALSE, pdTRUE, timeout);
    return (bits & WIFI_CONNECTED_BIT) != 0;
}

esp_err_t wifi_get_rssi(int *rssi_dbm)
{
    wifi_ap_record_t ap;
    esp_err_t err = esp_wifi_sta_get_ap_info(&ap);
    if (err == ESP_OK) {
        *rssi_dbm = ap.rssi;
    }
    return err;
}
