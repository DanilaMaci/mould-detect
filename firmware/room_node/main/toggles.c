#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "toggles.h"

static const char *TAG = "toggles";

#define POLL_MS       20
#define STABLE_POLLS  3     // a level must hold for 3 polls (60 ms) to count: contact bounce is shorter
#define TASK_STACK    3072

typedef struct {
    int button_gpio;        // to GND when pressed; internal pull-up
    int led_gpio;           // 330 Ohm + LED to GND
    const char *name;
    bool state;
    bool pressed;           // debounced button level
    int count;              // consecutive polls that disagree with `pressed`
} toggle_t;

static toggle_t toggles[TOGGLE_COUNT] = {
    [TOGGLE_WINDOW_OPEN] = { .button_gpio = 25, .led_gpio = 27, .name = "window open" },
    [TOGGLE_DOOR_OPEN]   = { .button_gpio = 26, .led_gpio = 32, .name = "door open", .state = true },
};
static TaskHandle_t notify_task;

// Feed one raw sample; returns true when the state flips. It flips on a clean press only, so holding the button
// or bouncing contacts count once, and the release does nothing.
static bool debounce(toggle_t *t, bool raw_pressed)
{
    if (raw_pressed == t->pressed) {
        t->count = 0;
        return false;
    }
    if (++t->count < STABLE_POLLS) return false;
    t->pressed = raw_pressed;
    t->count = 0;
    if (!raw_pressed) return false;
    t->state = !t->state;
    return true;
}

static void poll_once(void)
{
    for (int i = 0; i < TOGGLE_COUNT; i++) {
        toggle_t *t = &toggles[i];
        if (debounce(t, gpio_get_level(t->button_gpio) == 0)) {
            gpio_set_level(t->led_gpio, t->state);
            ESP_LOGI(TAG, "%s: %s", t->name, t->state ? "yes" : "no");
            if (notify_task) xTaskNotifyGive(notify_task);
        }
    }
}

static void poll_task(void *arg)
{
    (void)arg;
    while (1) {
        poll_once();
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

esp_err_t toggles_start(TaskHandle_t notify)
{
    notify_task = notify;
    for (int i = 0; i < TOGGLE_COUNT; i++) {
        gpio_config_t button = {
            .pin_bit_mask = 1ULL << toggles[i].button_gpio,
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
        };
        gpio_config_t led = {
            .pin_bit_mask = 1ULL << toggles[i].led_gpio,
            .mode = GPIO_MODE_OUTPUT,
        };
        esp_err_t err = gpio_config(&button);
        if (err == ESP_OK) err = gpio_config(&led);
        if (err != ESP_OK) return err;
        gpio_set_level(toggles[i].led_gpio, toggles[i].state);
        // A button that already reads pressed is a wiring fault (GPIO tied to GND) or someone holding it: start
        // from that level so it does not count as a press, and say so
        toggles[i].pressed = (gpio_get_level(toggles[i].button_gpio) == 0);
        if (toggles[i].pressed) {
            ESP_LOGW(TAG, "%s button (GPIO%d) reads pressed at boot: check that its GPIO and GND legs are "
                     "diagonal and the button straddles the breadboard's middle gap",
                     toggles[i].name, toggles[i].button_gpio);
        }
    }
    if (xTaskCreate(poll_task, "toggles", TASK_STACK, NULL, 6, NULL) != pdPASS) return ESP_FAIL;
    return ESP_OK;
}

bool toggles_get(toggle_id_t id)
{
    return toggles[id].state;
}
