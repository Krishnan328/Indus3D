#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <ArduinoJson.h>

#include "config.h"
#include "adxl345_spi.h"
#include "bme280_i2c.h"
#include "crash_detector.h"
#include "shaper_streamer.h"
#include "serial_protocol.h"

// Hardware instances
static ADXL345_SPI   adxl(PIN_ADXL_CS);
static BME280_I2C    bme(PIN_BME_SDA, PIN_BME_SCL);
static CrashDetector crash(DEFAULT_CRASH_THRESHOLD_MG);
static ShaperStreamer shaper(adxl, TCP_STREAM_PORT);
static proto::LineReader serial_line;

// State variables
static uint32_t last_adxl_poll_us = 0;
static uint32_t last_bme_poll_ms  = 0;
static uint32_t last_telemetry_ms = 0;
static ChamberTelemetry last_env = {0.0f, 0.0f, 0.0f, false, 0};
static bool env_has_humidity = true;   // BMP280 (chip id 0x58) has no humidity channel

static void handleSerialCommand(const char* line) {
    proto::Command c = proto::parse(line);
    switch (c.cmd) {
    case proto::CMD_NONE:
        return;

    case proto::CMD_PING:
        Serial.println("PONG");
        return;

    case proto::CMD_STATUS:
        Serial.printf("// STATUS: fw=%s adxl=%s bme=%s crash_thresh=%u mg latched=%d shaper=%s\n",
                      FIRMWARE_VERSION,
                      adxl.isConnected() ? "OK" : "DISCONNECTED",
                      bme.isConnected() ? "OK" : "DISCONNECTED",
                      crash.getThreshold(),
                      crash.isCrashLatched() ? 1 : 0,
                      shaper.isRunning() ? "ACTIVE" : "IDLE");
        return;

    case proto::CMD_START_SHAPER: {
        if (c.bad_args) { Serial.println("// ERROR: START_SHAPER takes integers: [duration_s] [rate_hz] [baud]"); return; }
        if (shaper.isRunning()) { Serial.println("// ERROR: shaper session already running"); return; }
        long duration = c.has[0] ? c.arg[0] : SHAPER_DEFAULT_DURATION_S;
        long rate     = c.has[1] ? c.arg[1] : SHAPER_DEFAULT_RATE_HZ;
        long baud     = c.has[2] ? c.arg[2] : 0;
        if (duration < 1 || duration > SHAPER_MAX_DURATION_S) {
            Serial.printf("// ERROR: duration must be 1-%d s\n", SHAPER_MAX_DURATION_S);
            return;
        }
        if (rate < 100 || rate > SHAPER_MAX_RATE_HZ) {
            Serial.printf("// ERROR: rate must be 100-%d Hz\n", SHAPER_MAX_RATE_HZ);
            return;
        }
        if (baud != 0 && !ShaperStreamer::isAllowedBaud((uint32_t)baud)) {
            Serial.println("// ERROR: baud must be 115200, 230400, 460800 or 921600");
            return;
        }
        shaper.startSession((uint8_t)duration, (uint16_t)rate, true, (uint32_t)baud);
        return;
    }

    case proto::CMD_STOP_SHAPER:
        shaper.stopSession();
        adxl.setRate(ADXL345_SPI::RATE_200HZ);   // normal monitoring rate
        return;

    case proto::CMD_SET_CRASH_THRESHOLD: {
        if (c.bad_args || !c.has[0]) { Serial.println("// ERROR: SET_CRASH_THRESHOLD <mg>"); return; }
        if (c.arg[0] < MIN_CRASH_THRESHOLD_MG || c.arg[0] > MAX_CRASH_THRESHOLD_MG) {
            Serial.printf("// ERROR: threshold must be %d-%d mg\n", MIN_CRASH_THRESHOLD_MG, MAX_CRASH_THRESHOLD_MG);
            return;
        }
        crash.setThreshold((uint16_t)c.arg[0]);
        Serial.printf("// CRASH_THRESHOLD_UPDATED: %u mg\n", (unsigned)c.arg[0]);
        return;
    }

    case proto::CMD_RESET_CRASH:
        crash.resetCrash();
        Serial.println("// CRASH_RESET");
        return;

    default:
        Serial.println("// ERROR: unknown command (PING STATUS START_SHAPER STOP_SHAPER SET_CRASH_THRESHOLD RESET_CRASH)");
        return;
    }
}

// Drain pending serial input without ever blocking. At most 64 characters per call so the
// 200 Hz crash loop and the shaper stream are never starved by a chatty host.
static void pollSerial() {
    for (uint8_t n = 0; n < 64 && Serial.available(); ++n) {
        if (serial_line.push((char)Serial.read())) {
            handleSerialCommand(serial_line.line());
            serial_line.clear();
        }
    }
}

static void emitTelemetry(uint32_t now_ms) {
    BedTelemetry b = crash.getBedTelemetry();

    StaticJsonDocument<512> doc;
    JsonObject bed = doc.createNestedObject("bed_accel");
    bed["x_mg"]    = b.x_mg;
    bed["y_mg"]    = b.y_mg;
    bed["z_mg"]    = b.z_mg;
    bed["jerk_mg"] = b.current_jerk_mg;

    // A sensor that is missing or failed must read as null, not as 0.0 °C / 0 % / 0 hPa, which
    // downstream consumers (Klipper, Indus3D, dashboards) cannot tell from a real measurement.
    JsonObject ch = doc.createNestedObject("chamber");
    if (last_env.is_valid) {
        ch["temp_c"] = serialized(String(last_env.temperature_c, 1));
        if (env_has_humidity) ch["humidity_pct"] = serialized(String(last_env.humidity_pct, 1));
        else                  ch["humidity_pct"] = nullptr;
        ch["pressure_hpa"] = serialized(String(last_env.pressure_hpa, 1));
    } else {
        ch["temp_c"] = nullptr;
        ch["humidity_pct"] = nullptr;
        ch["pressure_hpa"] = nullptr;
    }

    doc["crash_detected"]     = crash.isCrashLatched();
    doc["crash_threshold_mg"] = crash.getThreshold();
    if (crash.isCrashLatched()) {
        const CrashEvent& e = crash.getLastCrashEvent();
        JsonObject info = doc.createNestedObject("crash_info");
        info["peak_jerk_mg"]  = e.jerk_mg;
        info["timestamp_ms"]  = e.timestamp_ms;
        JsonObject at = info.createNestedObject("accel_at_crash");
        at["x"] = e.accel_x_mg;
        at["y"] = e.accel_y_mg;
        at["z"] = e.accel_z_mg;
    }
    doc["adxl_ok"]    = adxl.isConnected();
    doc["bme_ok"]     = bme.isConnected();
    doc["uptime_sec"] = now_ms / 1000UL;

    serializeJson(doc, Serial);
    Serial.println();
}

void setup() {
    Serial.begin(SERIAL_DEFAULT_BAUD);
    delay(200);

    Serial.println("\n\n=======================================================");
    Serial.printf("  INDUS3D ESP8266 SENSOR HUB (v%s)\n", FIRMWARE_VERSION);
    Serial.println("=======================================================");

    // 1. Initialize ADXL345 on Hardware SPI
    Serial.print("[INIT] Connecting ADXL345 on SPI (CS=GPIO16)... ");
    if (adxl.begin()) {
        Serial.printf("SUCCESS! DEVID=0x%02X\n", adxl.getDeviceID());
    } else {
        Serial.println("FAILED! Check SPI connections.");
    }

    // 2. Initialize BME280/BMP280 on verified I2C pins (D3=SDA, D4=SCL)
    Serial.printf("[INIT] Connecting Environmental Sensor on I2C (SDA=GPIO%d, SCL=GPIO%d)... ",
                  PIN_BME_SDA, PIN_BME_SCL);
    if (bme.begin(BME280_I2C_ADDR_PRIMARY)) {
        Serial.printf("SUCCESS! Address=0x%02X, Chip ID=0x%02X (%s)\n",
                      bme.getAddress(), bme.getChipID(),
                      bme.getChipID() == 0x58 ? "BMP280" : "BME280");
        env_has_humidity = bme.getChipID() != 0x58;
        bme.read(last_env);
    } else {
        Serial.println("FAILED! Check I2C connections.");
    }

    last_adxl_poll_us = micros();
    last_bme_poll_ms  = millis();
    last_telemetry_ms = millis();
}

void loop() {
    uint32_t now_ms = millis();
    uint32_t now_us = micros();

    pollSerial();

    // =================================================================
    // MODE B: High-Speed Input Shaping Session (Prioritized if active)
    // =================================================================
    if (shaper.isRunning()) {
        shaper.handleStream();
        return; // High-rate streaming takes precedence
    }

    // =================================================================
    // MODE A: Real-Time Printing & Telemetry Mode
    // =================================================================

    // 1. ADXL345 Poll & Bed Crash Detection (200 Hz = every 5000 us)
    if (now_us - last_adxl_poll_us >= TELEMETRY_LOOP_INTERVAL_US) {
        last_adxl_poll_us = now_us;

        AccelDataMg sample;
        if (adxl.readMg(sample)) {
            bool crash_detected = crash.update(sample);
            if (crash_detected) {
                CrashEvent event = crash.getLastCrashEvent();
                // Immediate Klipper-side notification (the host daemon parses this exact line)
                Serial.printf("// Klipper: BED_CRASH_DETECTED jerk=%u mg (accel=[%+d, %+d, %+d] mg) -> Auto-pausing print!\n",
                              event.jerk_mg, event.accel_x_mg, event.accel_y_mg, event.accel_z_mg);
            }
        }
    }

    // 2. BME280 / BMP280 Chamber Sampling (every 2 seconds)
    if (now_ms - last_bme_poll_ms >= BME280_SAMPLE_INTERVAL_MS) {
        last_bme_poll_ms = now_ms;
        if (bme.isConnected()) {
            bme.read(last_env);
        } else {
            last_env.is_valid = false;
        }
    }

    // 3. Periodic Telemetry Output (1 Hz JSON string for the host daemon)
    if (now_ms - last_telemetry_ms >= SERIAL_TELEMETRY_INTERVAL_MS) {
        last_telemetry_ms = now_ms;
        emitTelemetry(now_ms);
    }
}
