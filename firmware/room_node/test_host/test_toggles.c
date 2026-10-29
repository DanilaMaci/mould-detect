// Host test of the window/door toggle buttons: start states, debounce, one flip per press, LED and notification.
// Run: test_host/run.sh
#include <stdio.h>
#include "../main/toggles.c"   // includes the static functions (debounce, poll_once)

static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

static int level[40];           // GPIO input levels (1 = released, pull-up)
static int led[40];
static int n_notified, n_configs, tasks_created;

esp_err_t gpio_config(const gpio_config_t *cfg)
{
    n_configs++;
    if (cfg->mode == GPIO_MODE_INPUT) CHECK(cfg->pull_up_en == GPIO_PULLUP_ENABLE);
    return ESP_OK;
}
int gpio_get_level(int gpio) { return level[gpio]; }
esp_err_t gpio_set_level(int gpio, uint32_t lvl) { led[gpio] = (int)lvl; return ESP_OK; }
void vTaskDelay(TickType_t ticks) { (void)ticks; }
BaseType_t xTaskCreate(void (*fn)(void *), const char *name, uint32_t stack, void *arg, int prio, TaskHandle_t *h)
{
    (void)fn; (void)name; (void)stack; (void)arg; (void)prio; (void)h;
    tasks_created++;
    return pdPASS;
}
void xTaskNotifyGive(TaskHandle_t task) { CHECK(task == (TaskHandle_t)0x1234); n_notified++; }

// Hold the window button at `pressed` for n polls
static void hold(int gpio, int pressed, int n)
{
    level[gpio] = !pressed;
    for (int i = 0; i < n; i++) poll_once();
}

int main(void)
{
    level[25] = level[26] = 1;
    CHECK(toggles_start((TaskHandle_t)0x1234) == ESP_OK);
    CHECK(n_configs == 4 && tasks_created == 1);
    // Boot: windows closed (LED off), door open (LED lit)
    CHECK(!toggles_get(TOGGLE_WINDOW_OPEN) && toggles_get(TOGGLE_DOOR_OPEN));
    CHECK(led[27] == 0 && led[32] == 1);

    // 1. Contact bounce (on/off every poll) never holds for 3 polls: nothing happens
    for (int i = 0; i < 10; i++) hold(25, i % 2, 1);
    hold(25, 0, 5);
    CHECK(!toggles_get(TOGGLE_WINDOW_OPEN) && n_notified == 0);

    // 2. A 2-poll glitch (40 ms) is ignored
    hold(25, 1, 2);
    hold(25, 0, 5);
    CHECK(!toggles_get(TOGGLE_WINDOW_OPEN) && n_notified == 0);

    // 3. A clean press flips once, lights the LED and wakes the node task; holding it does not flip again
    hold(25, 1, 50);
    CHECK(toggles_get(TOGGLE_WINDOW_OPEN) && led[27] == 1 && n_notified == 1);

    // 4. Release does nothing; the next press flips back and turns the LED off
    hold(25, 0, 5);
    CHECK(toggles_get(TOGGLE_WINDOW_OPEN) && n_notified == 1);
    hold(25, 1, 3);
    CHECK(!toggles_get(TOGGLE_WINDOW_OPEN) && led[27] == 0 && n_notified == 2);
    hold(25, 0, 5);

    // 5. The door button is independent: pressing it when the door is closed turns its LED off, window untouched
    hold(26, 1, 3);
    CHECK(!toggles_get(TOGGLE_DOOR_OPEN) && led[32] == 0 && !toggles_get(TOGGLE_WINDOW_OPEN) && led[27] == 0);

    // 6. A button already pressed (or shorted to GND) at boot is not a press: states keep their boot values,
    //    nothing is sent; after it is released, a real press works
    for (int i = 0; i < TOGGLE_COUNT; i++) { toggles[i].pressed = false; toggles[i].count = 0; }
    toggles[TOGGLE_WINDOW_OPEN].state = false;
    toggles[TOGGLE_DOOR_OPEN].state = true;
    n_notified = 0;
    level[25] = level[26] = 0;
    CHECK(toggles_start((TaskHandle_t)0x1234) == ESP_OK);
    for (int i = 0; i < 20; i++) poll_once();
    CHECK(!toggles_get(TOGGLE_WINDOW_OPEN) && toggles_get(TOGGLE_DOOR_OPEN) && n_notified == 0);
    CHECK(led[27] == 0 && led[32] == 1);
    hold(25, 0, 5);
    hold(25, 1, 3);
    CHECK(toggles_get(TOGGLE_WINDOW_OPEN) && n_notified == 1);

    printf(failures ? "%d check(s) failed\n" : "OK: all toggle host checks passed\n", failures);
    return failures != 0;
}
