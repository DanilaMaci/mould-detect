#pragma once
// Host stand-in, 100 Hz tick as in sdkconfig
#include <stdint.h>
typedef uint32_t TickType_t;
#define pdMS_TO_TICKS(ms) ((TickType_t)((ms) / 10))
