#pragma once

#include <Arduino.h>

// =====================================================================
// Hardware Pinout Definitions for ESP8266 (NodeMCU / Wemos D1 Mini)
// =====================================================================

// ADXL345 on Hardware SPI (HSPI)
// Use D0 (GPIO16) for CS to avoid ESP8266 GPIO15 boot-strap hang (boot mode 7,7)
#define PIN_ADXL_CS     16  // D0 (GPIO16, active low) - Safe from boot restrictions!
#define PIN_ADXL_SCK    14  // D5 (GPIO14, HSPI_CLK)
#define PIN_ADXL_MISO   12  // D6 (GPIO12, HSPI_MISO)
#define PIN_ADXL_MOSI   13  // D7 (GPIO13, HSPI_MOSI)

// BME280 / BMP280 on I2C
#define PIN_BME_SDA     0   // D3 (GPIO0) - Hardware Verified
#define PIN_BME_SCL     2   // D4 (GPIO2) - Hardware Verified
#define BME280_I2C_ADDR_PRIMARY   0x76
#define BME280_I2C_ADDR_SECONDARY 0x77

// Status LED (Built-in LED on NodeMCU/Wemos D1 Mini is GPIO2 / D4, active LOW)
#define PIN_STATUS_LED  2   // D4 (GPIO2)

// =====================================================================
// Operating Parameters & Timing Defaults
// =====================================================================

// =====================================================================
// Communication Interface Mode
// =====================================================================
// Set to false to run completely over USB Serial (instant boot, zero Wi-Fi delay)
#define ENABLE_WIFI                 false

// Mode A: Real-Time Printing & Telemetry Mode
#define TELEMETRY_LOOP_HZ           200     // 200 Hz sampling loop (5000 us)
#define TELEMETRY_LOOP_INTERVAL_US  (1000000UL / TELEMETRY_LOOP_HZ)

#define BME280_SAMPLE_INTERVAL_MS   2000    // 0.5 Hz chamber environment sampling (2 seconds)
#define SERIAL_TELEMETRY_INTERVAL_MS 1000   // 1 Hz serial telemetry output

// Bed Crash & Jerk Thresholds
#define DEFAULT_CRASH_THRESHOLD_MG  2000    // 2000 mg = 2.0g instantaneous delta
#define MIN_CRASH_THRESHOLD_MG      500     // 0.5g minimum configurable
#define MAX_CRASH_THRESHOLD_MG      8000    // 8.0g maximum configurable
#define CRASH_COOLDOWN_MS           5000    // 5 seconds between repeated auto-pause triggers

// Mode B: High-Speed Input Shaping Mode
#define SHAPER_DEFAULT_RATE_HZ      1600    // 1600 Hz default high-rate sampling
#define SHAPER_MAX_RATE_HZ          3200    // 3200 Hz max rate
#define SHAPER_DEFAULT_DURATION_S   5       // 5 seconds duration
#define SHAPER_MAX_DURATION_S      15       // 15 seconds max duration
#define TCP_STREAM_PORT             8266    // High-speed binary TCP streaming port

// =====================================================================
// Network & Moonraker Defaults
// =====================================================================
#define DEVICE_NAME             "ESP8266-BedHub"
#define FIRMWARE_VERSION        "1.0.0"
#define MDNS_HOSTNAME           "esp8266-bedhub"
#define HTTP_SERVER_PORT        80

#define DEFAULT_WIFI_SSID       "Your_WiFi_SSID"
#define DEFAULT_WIFI_PASS       "Your_WiFi_Password"
#define DEFAULT_AP_SSID         "ESP8266-BedHub-AP"
#define DEFAULT_AP_PASS         "bedhub1234"

#define DEFAULT_MOONRAKER_IP    "192.168.1.100"
#define DEFAULT_MOONRAKER_PORT  7125
#define MOONRAKER_PAUSE_ENDPOINT "/printer/print/pause"

// =====================================================================
// Persistent Storage (EEPROM / Flash) Structure
// =====================================================================
#define EEPROM_MAGIC 0x42454448  // "BEDH" in ASCII
#define EEPROM_SIZE  512

struct DeviceConfig {
    uint32_t magic;
    char wifi_ssid[33];
    char wifi_pass[65];
    char moonraker_ip[40];
    uint16_t moonraker_port;
    uint16_t crash_threshold_mg;
    bool auto_pause_enabled;
    bool serial_stream_enabled;
    uint32_t checksum;
};
