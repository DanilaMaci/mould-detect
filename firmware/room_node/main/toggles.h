#pragma once
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"

// Two push buttons that each toggle an "open" state shown on an LED (lit = open): people press them when they open
// or close a window or the door (stopgap until magnetic contacts are fitted). At boot the windows count as closed
// and the door as open, the usual state of this room.
typedef enum { TOGGLE_WINDOW_OPEN, TOGGLE_DOOR_OPEN, TOGGLE_COUNT } toggle_id_t;

// Configure the pins and start polling the buttons; `notify` gets a task notification after every change.
esp_err_t toggles_start(TaskHandle_t notify);

bool toggles_get(toggle_id_t id);
