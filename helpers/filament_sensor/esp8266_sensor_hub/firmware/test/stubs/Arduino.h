// Minimal host stand-in for Arduino.h so the pure firmware logic can be unit-tested with g++.
#pragma once
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <stddef.h>
uint32_t millis();
uint32_t micros();
extern uint32_t g_test_millis;      // tests drive the clock
