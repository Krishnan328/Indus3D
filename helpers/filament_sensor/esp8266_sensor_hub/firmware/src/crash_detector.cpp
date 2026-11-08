#include "crash_detector.h"
#include <math.h>

CrashDetector::CrashDetector(uint16_t threshold_mg)
    : _threshold_mg(threshold_mg),
      _has_prev_sample(false),
      _crash_latched(false),
      _window_start_ms(0),
      _window_max_jerk(0),
      _last_trigger_ms(0) {
    memset(&_prev_sample, 0, sizeof(_prev_sample));
    memset(&_last_crash, 0, sizeof(_last_crash));
    memset(&_telemetry, 0, sizeof(_telemetry));
}

void CrashDetector::setThreshold(uint16_t threshold_mg) {
    _threshold_mg = threshold_mg;
}

bool CrashDetector::update(const AccelDataMg& current_sample) {
    uint32_t now = millis();

    _telemetry.x_mg = current_sample.x;
    _telemetry.y_mg = current_sample.y;
    _telemetry.z_mg = current_sample.z;

    if (!_has_prev_sample) {
        _prev_sample = current_sample;
        _has_prev_sample = true;
        _telemetry.current_jerk_mg = 0;
        _window_start_ms = now;
        return false;
    }

    // Calculate instantaneous jerk delta: sqrt(dx^2 + dy^2 + dz^2)
    int64_t dx = (int64_t)current_sample.x - (int64_t)_prev_sample.x;
    int64_t dy = (int64_t)current_sample.y - (int64_t)_prev_sample.y;
    int64_t dz = (int64_t)current_sample.z - (int64_t)_prev_sample.z;

    int64_t sum_sq = (dx * dx) + (dy * dy) + (dz * dz);
    uint32_t jerk_mg = (uint32_t)lround(sqrt((double)sum_sq));

    _telemetry.current_jerk_mg = jerk_mg;

    // Track 1-second rolling peak jerk
    if (jerk_mg > _window_max_jerk) {
        _window_max_jerk = jerk_mg;
    }
    if (now - _window_start_ms >= 1000) {
        _telemetry.peak_jerk_1s_mg = _window_max_jerk;
        _window_max_jerk = jerk_mg;
        _window_start_ms = now;
    }

    _prev_sample = current_sample;

    // Evaluate Crash Condition
    bool new_crash_event = false;
    if (jerk_mg >= _threshold_mg) {
        // Latch crash state
        _crash_latched = true;

        // Check cooldown for re-triggering Moonraker pause actions
        if (now - _last_trigger_ms >= 3000) {
            new_crash_event = true;
            _last_trigger_ms = now;

            _last_crash.detected = true;
            _last_crash.timestamp_ms = now;
            _last_crash.jerk_mg = jerk_mg;
            _last_crash.accel_x_mg = current_sample.x;
            _last_crash.accel_y_mg = current_sample.y;
            _last_crash.accel_z_mg = current_sample.z;
            _last_crash.delta_x_mg = (int32_t)dx;
            _last_crash.delta_y_mg = (int32_t)dy;
            _last_crash.delta_z_mg = (int32_t)dz;
        } else if (jerk_mg > _last_crash.jerk_mg) {
            // Update peak jerk if higher within the same event burst
            _last_crash.jerk_mg = jerk_mg;
            _last_crash.accel_x_mg = current_sample.x;
            _last_crash.accel_y_mg = current_sample.y;
            _last_crash.accel_z_mg = current_sample.z;
        }
    }

    return new_crash_event;
}

void CrashDetector::resetCrash() {
    _crash_latched = false;
    _last_crash.detected = false;
    _window_max_jerk = 0;
}
