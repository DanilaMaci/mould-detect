#pragma once
#include <stdbool.h>
#include "esp_err.h"

// Bit-level 1-Wire master on one GPIO (open drain, external 4.7 kΩ pull-up to 3V3).
// Timing follows Maxim/Dallas application note 126 (standard speed).

esp_err_t ow_init(int gpio);

// Reset pulse. Returns ESP_OK if at least one device answered with a presence pulse,
// ESP_ERR_NOT_FOUND if none did, ESP_FAIL if the line stays low (short to GND or missing pull-up).
esp_err_t ow_reset(void);

void ow_write_bit(bool bit);
bool ow_read_bit(void);
