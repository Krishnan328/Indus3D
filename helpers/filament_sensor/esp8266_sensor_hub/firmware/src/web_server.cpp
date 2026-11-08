#include "web_server.h"

WebServerManager::WebServerManager(ADXL345_SPI& adxl,
                                   BME280_I2C& bme,
                                   CrashDetector& crash,
                                   ShaperStreamer& shaper,
                                   MoonrakerClient& moonraker,
                                   DeviceConfig& config)
    : _server(HTTP_SERVER_PORT),
      _adxl(adxl),
      _bme(bme),
      _crash(crash),
      _shaper(shaper),
      _moonraker(moonraker),
      _config(config) {}

void WebServerManager::begin() {
    _server.on("/", HTTP_GET, [this]() { handleRoot(); });
    _server.on("/telemetry", HTTP_GET, [this]() { handleTelemetry(); });
    _server.on("/chamber", HTTP_GET, [this]() { handleChamber(); });
    _server.on("/reset_crash", HTTP_POST, [this]() { handleResetCrash(); });
    _server.on("/reset_crash", HTTP_GET, [this]() { handleResetCrash(); }); // allow GET for quick browser test
    _server.on("/status", HTTP_GET, [this]() { handleStatus(); });
    _server.on("/config", HTTP_POST, [this]() { handleConfig(); });
    _server.on("/config", HTTP_GET, [this]() { handleStatus(); });
    _server.on("/shaper/start", HTTP_POST, [this]() { handleShaperStart(); });
    _server.on("/shaper/start", HTTP_GET, [this]() { handleShaperStart(); });
    _server.on("/shaper/status", HTTP_GET, [this]() { handleShaperStatus(); });

    _server.onNotFound([this]() { handleNotFound(); });

    _server.begin();
    Serial.println("[HTTP] REST API server started on port 80");
}

void WebServerManager::handleClient() {
    _server.handleClient();
}

void WebServerManager::addCorsHeaders() {
    _server.sendHeader("Access-Control-Allow-Origin", "*");
    _server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    _server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

void WebServerManager::handleRoot() {
    addCorsHeaders();
    String html = "<!DOCTYPE html><html><head><title>ESP8266 Sensor Hub</title>";
    html += "<style>body{font-family:sans-serif;margin:2rem;background:#1e1e2e;color:#cdd6f4;}";
    html += "a{color:#89b4fa;}pre{background:#11111b;padding:1rem;border-radius:8px;}</style></head><body>";
    html += "<h1>ESP8266 Multi-Sensor Hub (Indus3D)</h1>";
    html += "<p>Bed Collision Monitor + Automated Input Shaping + Chamber Telemetry</p>";
    html += "<ul>";
    html += "<li><a href='/telemetry'>/telemetry</a> - Real-time bed acceleration & chamber readings</li>";
    html += "<li><a href='/chamber'>/chamber</a> - Dedicated chamber endpoint for Klipper</li>";
    html += "<li><a href='/status'>/status</a> - System diagnostics & hardware health</li>";
    html += "<li><a href='/shaper/status'>/shaper/status</a> - Input shaper streaming status</li>";
    html += "</ul></body></html>";
    _server.send(200, "text/html", html);
}

void WebServerManager::handleTelemetry() {
    addCorsHeaders();

    StaticJsonDocument<512> doc;
    const BedTelemetry& bed = _crash.getBedTelemetry();

    // Bed acceleration object
    JsonObject bed_obj = doc.createNestedObject("bed_accel");
    bed_obj["x_mg"] = bed.x_mg;
    bed_obj["y_mg"] = bed.y_mg;
    bed_obj["z_mg"] = bed.z_mg;
    bed_obj["jerk_mg"] = bed.current_jerk_mg;

    // Chamber object
    ChamberTelemetry chamber_data;
    bool bme_ok = _bme.read(chamber_data);
    JsonObject chamber_obj = doc.createNestedObject("chamber");
    if (bme_ok && chamber_data.is_valid) {
        chamber_obj["temp_c"] = serialized(String(chamber_data.temperature_c, 1));
        chamber_obj["humidity_pct"] = serialized(String(chamber_data.humidity_pct, 1));
        chamber_obj["pressure_hpa"] = serialized(String(chamber_data.pressure_hpa, 1));
    } else {
        chamber_obj["temp_c"] = nullptr;
        chamber_obj["humidity_pct"] = nullptr;
        chamber_obj["pressure_hpa"] = nullptr;
    }

    doc["crash_detected"] = _crash.isCrashLatched();
    doc["uptime_sec"] = millis() / 1000UL;

    if (_crash.isCrashLatched()) {
        const CrashEvent& crash = _crash.getLastCrashEvent();
        JsonObject crash_info = doc.createNestedObject("crash_info");
        crash_info["timestamp_ms"] = crash.timestamp_ms;
        crash_info["peak_jerk_mg"] = crash.jerk_mg;
        JsonObject accel_at_crash = crash_info.createNestedObject("accel_at_crash");
        accel_at_crash["x"] = crash.accel_x_mg;
        accel_at_crash["y"] = crash.accel_y_mg;
        accel_at_crash["z"] = crash.accel_z_mg;
    }

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleChamber() {
    addCorsHeaders();

    ChamberTelemetry chamber_data;
    bool bme_ok = _bme.read(chamber_data);

    StaticJsonDocument<256> doc;
    if (bme_ok && chamber_data.is_valid) {
        doc["temperature"] = serialized(String(chamber_data.temperature_c, 2));
        doc["humidity"] = serialized(String(chamber_data.humidity_pct, 1));
        doc["pressure"] = serialized(String(chamber_data.pressure_hpa, 1));
    } else {
        doc["temperature"] = 0.0;
        doc["humidity"] = 0.0;
        doc["pressure"] = 0.0;
    }

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleResetCrash() {
    addCorsHeaders();
    _crash.resetCrash();

    StaticJsonDocument<128> doc;
    doc["status"] = "ok";
    doc["message"] = "Crash latch cleared successfully";
    doc["crash_detected"] = false;

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleStatus() {
    addCorsHeaders();

    StaticJsonDocument<512> doc;
    doc["device"] = DEVICE_NAME;
    doc["version"] = FIRMWARE_VERSION;
    doc["ip"] = WiFi.localIP().toString();
    doc["rssi"] = WiFi.RSSI();
    doc["adxl345_online"] = _adxl.isConnected();
    doc["bme280_online"] = _bme.isConnected();
    doc["crash_latched"] = _crash.isCrashLatched();
    doc["crash_threshold_mg"] = _crash.getThreshold();
    doc["moonraker_target"] = _moonraker.getHost() + ":" + String(_moonraker.getPort());
    doc["shaper_active"] = _shaper.isRunning();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["uptime_sec"] = millis() / 1000UL;

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleConfig() {
    addCorsHeaders();

    if (_server.hasArg("plain")) {
        StaticJsonDocument<256> doc;
        DeserializationError err = deserializeJson(doc, _server.arg("plain"));
        if (!err) {
            if (doc.containsKey("threshold_mg")) {
                uint16_t t = doc["threshold_mg"];
                if (t >= MIN_CRASH_THRESHOLD_MG && t <= MAX_CRASH_THRESHOLD_MG) {
                    _crash.setThreshold(t);
                    _config.crash_threshold_mg = t;
                }
            }
            if (doc.containsKey("moonraker_ip")) {
                const char* hip = doc["moonraker_ip"];
                strncpy(_config.moonraker_ip, hip, sizeof(_config.moonraker_ip) - 1);
                _moonraker.setTarget(_config.moonraker_ip, _config.moonraker_port);
            }
            if (doc.containsKey("moonraker_port")) {
                _config.moonraker_port = doc["moonraker_port"];
                _moonraker.setTarget(_config.moonraker_ip, _config.moonraker_port);
            }
        }
    } else {
        if (_server.hasArg("threshold_mg")) {
            uint16_t t = _server.arg("threshold_mg").toInt();
            if (t >= MIN_CRASH_THRESHOLD_MG && t <= MAX_CRASH_THRESHOLD_MG) {
                _crash.setThreshold(t);
                _config.crash_threshold_mg = t;
            }
        }
        if (_server.hasArg("moonraker_ip")) {
            strncpy(_config.moonraker_ip, _server.arg("moonraker_ip").c_str(), sizeof(_config.moonraker_ip) - 1);
            _moonraker.setTarget(_config.moonraker_ip, _config.moonraker_port);
        }
    }

    handleStatus();
}

void WebServerManager::handleShaperStart() {
    addCorsHeaders();

    uint8_t duration_s = SHAPER_DEFAULT_DURATION_S;
    uint16_t rate_hz = SHAPER_DEFAULT_RATE_HZ;

    if (_server.hasArg("duration")) {
        duration_s = _server.arg("duration").toInt();
    }
    if (_server.hasArg("rate")) {
        rate_hz = _server.arg("rate").toInt();
    }

    bool started = _shaper.startSession(duration_s, rate_hz);

    StaticJsonDocument<256> doc;
    doc["status"] = started ? "started" : "error";
    doc["duration_s"] = duration_s;
    doc["rate_hz"] = rate_hz;
    doc["tcp_stream_port"] = TCP_STREAM_PORT;
    doc["message"] = "Connect to TCP port 8266 to stream binary acceleration frames";

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleShaperStatus() {
    addCorsHeaders();

    StaticJsonDocument<256> doc;
    doc["running"] = _shaper.isRunning();
    doc["samples_recorded"] = _shaper.getSampleCount();
    doc["rate_hz"] = _shaper.getRateHz();
    doc["duration_s"] = _shaper.getDurationS();
    doc["has_tcp_client"] = _shaper.hasTcpClient();

    String response;
    serializeJson(doc, response);
    _server.send(200, "application/json", response);
}

void WebServerManager::handleNotFound() {
    if (_server.method() == HTTP_OPTIONS) {
        addCorsHeaders();
        _server.send(204);
        return;
    }
    addCorsHeaders();
    _server.send(404, "application/json", "{\"error\":\"Endpoint not found\"}");
}
