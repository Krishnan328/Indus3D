#include "network_manager.h"

NetworkManager::NetworkManager(DeviceConfig& config)
    : _config(config),
      _ap_mode(false),
      _last_reconnect_attempt(0) {}

void NetworkManager::begin() {
    startStation();
}

void NetworkManager::startStation() {
    _ap_mode = false;
    WiFi.mode(WIFI_STA);
    WiFi.hostname(MDNS_HOSTNAME);

    Serial.printf("[WiFi] Connecting to %s...\n", _config.wifi_ssid);
    WiFi.begin(_config.wifi_ssid, _config.wifi_pass);

    uint32_t start_time = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start_time < 8000)) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[WiFi] Connected! IP: %s, RSSI: %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
        if (MDNS.begin(MDNS_HOSTNAME)) {
            Serial.printf("[mDNS] Responder started at http://%s.local\n", MDNS_HOSTNAME);
            MDNS.addService("http", "tcp", 80);
        }
    } else {
        Serial.println("[WiFi] Connection timed out. Starting fallback SoftAP mode...");
        startAP();
    }
}

void NetworkManager::startAP() {
    _ap_mode = true;
    WiFi.mode(WIFI_AP);
    WiFi.softAP(DEFAULT_AP_SSID, DEFAULT_AP_PASS);
    Serial.printf("[WiFi] SoftAP started: SSID='%s', IP=%s\n", DEFAULT_AP_SSID, WiFi.softAPIP().toString().c_str());

    if (MDNS.begin(MDNS_HOSTNAME)) {
        MDNS.addService("http", "tcp", 80);
    }
}

void NetworkManager::update() {
    MDNS.update();

    // Auto-reconnect in Station mode if dropped
    if (!_ap_mode && WiFi.status() != WL_CONNECTED) {
        uint32_t now = millis();
        if (now - _last_reconnect_attempt >= 15000) {
            _last_reconnect_attempt = now;
            Serial.println("[WiFi] Reconnecting to AP...");
            WiFi.reconnect();
        }
    }
}

bool NetworkManager::isConnected() const {
    return (_ap_mode || WiFi.status() == WL_CONNECTED);
}

String NetworkManager::getIP() const {
    if (_ap_mode) {
        return WiFi.softAPIP().toString();
    }
    return WiFi.localIP().toString();
}
