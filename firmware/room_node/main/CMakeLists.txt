idf_component_register(SRCS "main.c" "i2c_bus.c" "bme280.c" "scd40.c" "onewire.c" "ds18b20.c" "toggles.c" "wifi.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_driver_gpio esp_wifi nvs_flash
                                     esp_netif esp_event esp_http_client mbedtls)
