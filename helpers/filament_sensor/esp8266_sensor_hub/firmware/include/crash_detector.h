#pragma once

#include <Arduino.h>
#include "adxl345_spi.h"

struct CrashEvent {
    bool detected;
    uint32_t timestamp_ms;
    uint32_t jerk_mg;
    int32_t accel_x_mg;
    int32_t accel_y_mg;
    int32_t accel_z_mg;
    int32_t delta_x_mg;
    int32_t delta_y_mg;
    int32_t delta_z_mg;
};

struct BedTelemetry {
    int32_t x_mg;
    int32_t y_mg;
    int32_t z_mg;
    uint32_t current_jerk_mg;
    uint32_t peak_jerk_1s_mg;
};

class CrashDetector {
public:
    CrashDetector(uint16_t threshold_mg = 2000);

    void setThreshold(uint16_t threshold_mg);
    uint16_t getThreshold() const { return _threshold_mg; }

    // Process new sample from 200 Hz loop
    // Returns true if a NEW crash was triggered on this sample
    bool update(const AccelDataMg& current_sample);

    bool isCrashLatched() const { return _crash_latched; }
    void resetCrash();

    const CrashEvent& getLastCrashEvent() const { return _last_crash; }
    const BedTelemetry& getBedTelemetry() const { return _telemetry; }

private:
    uint16_t _threshold_mg;
    bool _has_prev_sample;
    AccelDataMg _prev_sample;

    bool _crash_latched;
    CrashEvent _last_crash;
    BedTelemetry _telemetry;

    // Window peak tracking
    uint32_t _window_start_ms;
    uint32_t _window_max_jerk;

    // Cooldown to avoid flooding HTTP pause calls
    uint32_t _last_trigger_ms;
    bool _ever_triggered;
};
