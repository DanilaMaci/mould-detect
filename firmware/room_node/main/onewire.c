#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "onewire.h"

static int pin = -1;
// Interrupts are off during each time slot: a Wi-Fi interrupt inside a slot would stretch it
// beyond what the probe accepts. Each critical section lasts at most ~70 µs.
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

esp_err_t ow_init(int gpio)
{
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << gpio,
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,      // drive low or let go; the pull-up makes the high
        .pull_up_en = GPIO_PULLUP_ENABLE,       // ~45 kΩ internal, too weak alone: 4.7 kΩ is still needed
    };
    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) return err;
    pin = gpio;
    gpio_set_level(pin, 1);
    return ESP_OK;
}

esp_err_t ow_reset(void)
{
    gpio_set_level(pin, 0);
    esp_rom_delay_us(480);                      // a longer low pulse does no harm, so this part may be interrupted

    portENTER_CRITICAL(&mux);
    gpio_set_level(pin, 1);
    esp_rom_delay_us(70);
    int presence = gpio_get_level(pin);         // 0: a device pulls the line low
    portEXIT_CRITICAL(&mux);

    esp_rom_delay_us(410);                      // rest of the presence window
    if (gpio_get_level(pin) == 0) return ESP_FAIL;
    return presence == 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
}

void ow_write_bit(bool bit)
{
    portENTER_CRITICAL(&mux);
    gpio_set_level(pin, 0);
    esp_rom_delay_us(bit ? 2 : 60);             // short low = 1, long low = 0
    gpio_set_level(pin, 1);
    portEXIT_CRITICAL(&mux);
    esp_rom_delay_us(bit ? 60 : 5);             // finish the 60 µs slot, then recovery
}

bool ow_read_bit(void)
{
    portENTER_CRITICAL(&mux);
    gpio_set_level(pin, 0);
    esp_rom_delay_us(2);
    gpio_set_level(pin, 1);
    esp_rom_delay_us(10);                       // sample before 15 µs: the probe's data is valid until then
    int level = gpio_get_level(pin);
    portEXIT_CRITICAL(&mux);
    esp_rom_delay_us(50);
    return level != 0;
}
