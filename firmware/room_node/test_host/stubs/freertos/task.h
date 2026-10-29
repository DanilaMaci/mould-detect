#pragma once
#include "FreeRTOS.h"
typedef void *TaskHandle_t;
typedef int BaseType_t;
#define pdPASS 1
void vTaskDelay(TickType_t ticks);
BaseType_t xTaskCreate(void (*fn)(void *), const char *name, uint32_t stack, void *arg, int prio, TaskHandle_t *h);
void xTaskNotifyGive(TaskHandle_t task);
