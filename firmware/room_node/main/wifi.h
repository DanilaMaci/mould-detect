#pragma once
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "esp_err.h"

// Start Wi-Fi in station mode with automatic backoff reconnect.
void wifi_start(void);

// Wait up to `timeout` ticks for a connection. Returns true if connected.
bool wifi_wait_connected(TickType_t timeout);

// Current signal strength of the connected router, in dBm.
esp_err_t wifi_get_rssi(int *rssi_dbm);
