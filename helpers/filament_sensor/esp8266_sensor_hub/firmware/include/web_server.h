#pragma once

#include <Arduino.h>
#include <ESP8266WebServer.h>
#include <ArduinoJson.h>
#include "adxl345_spi.h"
#include "bme280_i2c.h"
#include "crash_detector.h"
#include "shaper_streamer.h"
#include "moonraker_client.h"
#include "config.h"

class WebServerManager {
public:
    WebServerManager(ADXL345_SPI& adxl,
                     BME280_I2C& bme,
                     CrashDetector& crash,
                     ShaperStreamer& shaper,
                     MoonrakerClient& moonraker,
                     DeviceConfig& config);

    void begin();
    void handleClient();

private:
    ESP8266WebServer _server;
    ADXL345_SPI& _adxl;
    BME280_I2C& _bme;
    CrashDetector& _crash;
    ShaperStreamer& _shaper;
    MoonrakerClient& _moonraker;
    DeviceConfig& _config;

    void handleRoot();
    void handleTelemetry();
    void handleChamber();
    void handleResetCrash();
    void handleStatus();
    void handleConfig();
    void handleShaperStart();
    void handleShaperStatus();
    void handleNotFound();

    void addCorsHeaders();
};
