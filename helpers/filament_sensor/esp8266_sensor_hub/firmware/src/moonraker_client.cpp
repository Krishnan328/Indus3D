#include "moonraker_client.h"

MoonrakerClient::MoonrakerClient(const char* host, uint16_t port)
    : _host(host), _port(port) {}

void MoonrakerClient::setTarget(const char* host, uint16_t port) {
    _host = host;
    _port = port;
}

bool MoonrakerClient::sendPause(uint32_t jerk_mg) {
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    HTTPClient http;
    http.setTimeout(800); // Short timeout to avoid stalling

    String url = "http://" + _host + ":" + String(_port) + "/printer/print/pause";
    if (!http.begin(_wifi_client, url)) {
        return false;
    }

    http.addHeader("Content-Type", "application/json");
    int http_code = http.POST("{}");
    http.end();

    // Also trigger custom Bed Crash Handler macro if configured
    char gcode_buf[64];
    snprintf(gcode_buf, sizeof(gcode_buf), "BED_CRASH_HANDLER JERK=%u", jerk_mg);
    sendGcode(gcode_buf);

    return (http_code == 200 || http_code == 204);
}

bool MoonrakerClient::sendGcode(const char* gcode) {
    if (WiFi.status() != WL_CONNECTED || !gcode) {
        return false;
    }

    HTTPClient http;
    http.setTimeout(800);

    String url = "http://" + _host + ":" + String(_port) + "/printer/gcode/script";
    if (!http.begin(_wifi_client, url)) {
        return false;
    }

    http.addHeader("Content-Type", "application/json");
    String payload = "{\"script\":\"" + String(gcode) + "\"}";
    int http_code = http.POST(payload);
    http.end();

    return (http_code == 200 || http_code == 204);
}

bool MoonrakerClient::ping() {
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    HTTPClient http;
    http.setTimeout(500);

    String url = "http://" + _host + ":" + String(_port) + "/printer/info";
    if (!http.begin(_wifi_client, url)) {
        return false;
    }

    int http_code = http.GET();
    http.end();

    return (http_code == 200);
}
