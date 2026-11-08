#include "shaper_streamer.h"

ShaperStreamer::ShaperStreamer(ADXL345_SPI& adxl, uint16_t tcp_port)
    : _adxl(adxl),
      _tcp_port(tcp_port),
      _server(tcp_port),
      _is_running(false),
      _stream_to_serial(false),
      _duration_s(5),
      _rate_hz(1600),
      _interval_us(625),
      _session_start_ms(0),
      _next_sample_us(0),
      _sample_count(0),
      _packet_seq(0),
      _batch_index(0) {}

void ShaperStreamer::begin() {
    _server.begin();
    _server.setNoDelay(true);
}

bool ShaperStreamer::hasTcpClient() {
    if (_server.hasClient()) {
        if (!_client || !_client.connected()) {
            _client = _server.accept();
            _client.setNoDelay(true);
        }
    }
    return (_client && _client.connected());
}

bool ShaperStreamer::startSession(uint8_t duration_s, uint16_t rate_hz, bool stream_to_serial) {
    if (duration_s == 0) duration_s = 5;
    if (duration_s > 15) duration_s = 15; // Cap at 15s

    _duration_s = duration_s;
    _stream_to_serial = stream_to_serial;
    _rate_hz = (rate_hz >= 3200) ? 3200 : 1600;
    _interval_us = 1000000UL / _rate_hz;

    // Switch ADXL345 to high rate
    if (_rate_hz >= 3200) {
        _adxl.setRate(ADXL345_SPI::RATE_3200HZ);
    } else {
        _adxl.setRate(ADXL345_SPI::RATE_1600HZ);
    }

    _sample_count = 0;
    _packet_seq = 0;
    _batch_index = 0;
    _session_start_ms = millis();
    _next_sample_us = micros();
    _is_running = true;

    Serial.printf("// SHAPER_SESSION_STARTED: duration=%u s, rate=%u Hz\n", _duration_s, _rate_hz);
    return true;
}

void ShaperStreamer::stopSession() {
    if (!_is_running) return;

    flushBatch();
    _is_running = false;

    // Revert ADXL345 back to 200 Hz for Mode A
    _adxl.setRate(ADXL345_SPI::RATE_200HZ);

    Serial.printf("// SHAPER_SESSION_ENDED: collected %u samples\n", _sample_count);
}

void ShaperStreamer::handleStream() {
    // Check for incoming TCP connections
    hasTcpClient();

    if (!_is_running) return;

    // Check duration timeout
    if (millis() - _session_start_ms >= (uint32_t)_duration_s * 1000UL) {
        stopSession();
        return;
    }

    uint32_t now_us = micros();
    if ((int32_t)(now_us - _next_sample_us) >= 0) {
        _next_sample_us += _interval_us;

        AccelDataRaw raw;
        if (_adxl.readRaw(raw)) {
            ShaperBinaryPacket& pkt = _batch_buffer[_batch_index++];
            pkt.magic[0] = 0xAA;
            pkt.magic[1] = 0x55;
            pkt.seq = _packet_seq++;
            pkt.timestamp_us = now_us;
            pkt.x_raw = raw.x;
            pkt.y_raw = raw.y;
            pkt.z_raw = raw.z;
            pkt.checksum = calculateChecksum(pkt);

            _sample_count++;

            if (_batch_index >= BATCH_SIZE) {
                flushBatch();
            }
        }
    }
}

void ShaperStreamer::flushBatch() {
    if (_batch_index == 0) return;

    size_t bytes_to_send = _batch_index * sizeof(ShaperBinaryPacket);

    if (_stream_to_serial) {
        Serial.write((const uint8_t*)_batch_buffer, bytes_to_send);
    }

    if (_client && _client.connected()) {
        _client.write((const uint8_t*)_batch_buffer, bytes_to_send);
    }

    _batch_index = 0;
}

uint8_t ShaperStreamer::calculateChecksum(const ShaperBinaryPacket& pkt) {
    const uint8_t* p = (const uint8_t*)&pkt;
    uint8_t cs = 0;
    // XOR the first 14 bytes (excluding checksum itself)
    for (size_t i = 0; i < sizeof(ShaperBinaryPacket) - 1; ++i) {
        cs ^= p[i];
    }
    return cs;
}
