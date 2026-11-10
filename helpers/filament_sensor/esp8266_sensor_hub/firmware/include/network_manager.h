#pragma once

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include "config.h"

class NetworkManager {
public:
    NetworkManager(DeviceConfig& config);

    void begin();
    void update();

    bool isConnected() const;
    bool isAPMode() const { return _ap_mode; }
    String getIP() const;

private:
    DeviceConfig& _config;
    bool _ap_mode;
    uint32_t _last_reconnect_attempt;

    void startStation();
    void startAP();
};
