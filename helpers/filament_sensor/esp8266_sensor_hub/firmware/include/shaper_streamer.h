#pragma once

#include <Arduino.h>
#include <WiFiServer.h>
#include <WiFiClient.h>
#include "adxl345_spi.h"

// Binary Packet Structure for High-Speed Streaming (15 bytes)
#pragma pack(push, 1)
struct ShaperBinaryPacket {
    uint8_t  magic[2];      // 0xAA, 0x55
    uint16_t seq;           // Monotonic packet sequence counter
    uint32_t timestamp_us;  // Microsecond timestamp from ESP8266 micros()
    int16_t  x_raw;         // Raw 16-bit 2's complement X
    int16_t  y_raw;         // Raw 16-bit 2's complement Y
    int16_t  z_raw;         // Raw 16-bit 2's complement Z
    uint8_t  checksum;      // XOR checksum of previous 14 bytes
};
#pragma pack(pop)

class ShaperStreamer {
public:
    ShaperStreamer(ADXL345_SPI& adxl, uint16_t tcp_port = 8266);

    void begin();

    // Start a high-speed sampling session
    bool startSession(uint8_t duration_s = 5, uint16_t rate_hz = 1600, bool stream_to_serial = false);
    void stopSession();

    void setStreamToSerial(bool enable) { _stream_to_serial = enable; }
    bool isStreamingToSerial() const { return _stream_to_serial; }

    // Polling function to be called in loop() when session is active
    void handleStream();

    bool isRunning() const { return _is_running; }
    uint32_t getSampleCount() const { return _sample_count; }
    uint16_t getRateHz() const { return _rate_hz; }
    uint8_t getDurationS() const { return _duration_s; }

    // Check if TCP client is connected
    bool hasTcpClient();

private:
    ADXL345_SPI& _adxl;
    uint16_t _tcp_port;
    WiFiServer _server;
    WiFiClient _client;

    bool _is_running;
    bool _stream_to_serial;
    uint8_t _duration_s;
    uint16_t _rate_hz;
    uint32_t _interval_us;
    uint32_t _session_start_ms;
    uint32_t _next_sample_us;
    uint32_t _sample_count;
    uint16_t _packet_seq;

    // Batch buffer for TCP transmission efficiency (batch 16 packets = 240 bytes)
    static constexpr uint8_t BATCH_SIZE = 16;
    ShaperBinaryPacket _batch_buffer[BATCH_SIZE];
    uint8_t _batch_index;

    void flushBatch();
    uint8_t calculateChecksum(const ShaperBinaryPacket& pkt);
};
