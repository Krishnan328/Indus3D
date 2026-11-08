#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <ArduinoJson.h>

#include "config.h"
#include "adxl345_spi.h"
#include "bme280_i2c.h"
#include "crash_detector.h"
#include "shaper_streamer.h"

// Hardware instances
static ADXL345_SPI   adxl(PIN_ADXL_CS);
static BME280_I2C    bme(PIN_BME_SDA, PIN_BME_SCL);
static CrashDetector crash(DEFAULT_CRASH_THRESHOLD_MG);
static ShaperStreamer shaper(adxl, TCP_STREAM_PORT);

// State variables
static uint32_t last_adxl_poll_us = 0;
static uint32_t last_bme_poll_ms  = 0;
static uint32_t last_telemetry_ms = 0;
static ChamberTelemetry last_env = {0.0f, 0.0f, 0.0f, false, 0};

static void handleSerialCommand(const String& cmd) {
    String cleanCmd = cmd;
    cleanCmd.trim();
    if (cleanCmd.length() == 0) return;

    if (cleanCmd.equalsIgnoreCase("PING")) {
        Serial.println("PONG");
    } else if (cleanCmd.equalsIgnoreCase("STATUS")) {
        Serial.printf("// STATUS: adxl=%s bme=%s crash_thresh=%u mg shaper=%s\n",
                      adxl.isConnected() ? "OK" : "DISCONNECTED",
                      bme.isConnected() ? "OK" : "DISCONNECTED",
                      crash.getThreshold(),
                      shaper.isRunning() ? "ACTIVE" : "IDLE");
    } else if (cleanCmd.startsWith("START_SHAPER")) {
        // Syntax: START_SHAPER [duration_s] [rate_hz]
        int duration = SHAPER_DEFAULT_DURATION_S;
        int rate = SHAPER_DEFAULT_RATE_HZ;
        int firstSpace = cleanCmd.indexOf(' ');
        if (firstSpace > 0) {
            int secondSpace = cleanCmd.indexOf(' ', firstSpace + 1);
            if (secondSpace > 0) {
                duration = cleanCmd.substring(firstSpace + 1, secondSpace).toInt();
                rate = cleanCmd.substring(secondSpace + 1).toInt();
            } else {
                duration = cleanCmd.substring(firstSpace + 1).toInt();
            }
        }
        shaper.startSession(duration, rate, true);
    } else if (cleanCmd.equalsIgnoreCase("STOP_SHAPER")) {
        shaper.stopSession();
        // Restore ADXL rate for normal monitoring
        adxl.setRate(ADXL345_SPI::RATE_200HZ);
    } else if (cleanCmd.startsWith("SET_CRASH_THRESHOLD")) {
        int space = cleanCmd.indexOf(' ');
        if (space > 0) {
            uint16_t thresh = cleanCmd.substring(space + 1).toInt();
            if (thresh >= MIN_CRASH_THRESHOLD_MG && thresh <= MAX_CRASH_THRESHOLD_MG) {
                crash.setThreshold(thresh);
                Serial.printf("// CRASH_THRESHOLD_UPDATED: %u mg\n", thresh);
            }
        }
    }
}

void setup() {
    Serial.begin(115200);
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

    // Check serial input commands
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        handleSerialCommand(line);
    }

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
                // Send immediate Klipper notification over serial
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
        }
    }

    // 3. Periodic Telemetry Output (1 Hz JSON string for host daemon)
    if (now_ms - last_telemetry_ms >= SERIAL_TELEMETRY_INTERVAL_MS) {
        last_telemetry_ms = now_ms;

        BedTelemetry b_telem = crash.getBedTelemetry();

        StaticJsonDocument<256> doc;
        JsonObject bed = doc.createNestedObject("bed_accel");
        bed["x_mg"]    = b_telem.x_mg;
        bed["y_mg"]    = b_telem.y_mg;
        bed["z_mg"]    = b_telem.z_mg;
        bed["jerk_mg"] = b_telem.current_jerk_mg;

        JsonObject ch = doc.createNestedObject("chamber");
        ch["temp_c"]       = serialized(String(last_env.temperature_c, 1));
        ch["humidity_pct"] = serialized(String(last_env.humidity_pct, 1));
        ch["pressure_hpa"] = serialized(String(last_env.pressure_hpa, 1));

        doc["crash_detected"] = crash.isCrashLatched();
        doc["uptime_sec"]     = now_ms / 1000UL;

        serializeJson(doc, Serial);
        Serial.println();
    }
}
