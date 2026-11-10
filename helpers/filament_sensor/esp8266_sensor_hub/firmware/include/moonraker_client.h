#pragma once

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>

class MoonrakerClient {
public:
    MoonrakerClient(const char* host = "192.168.1.100", uint16_t port = 7125);

    void setTarget(const char* host, uint16_t port);
    const String& getHost() const { return _host; }
    uint16_t getPort() const { return _port; }

    // Send pause command to Moonraker
    bool sendPause(uint32_t jerk_mg);

    // Send emergency G-code macro trigger
    bool sendGcode(const char* gcode);

    // Check if Moonraker API is reachable
    bool ping();

private:
    String _host;
    uint16_t _port;
    WiFiClient _wifi_client;
};
