#include "shaper_streamer.h"
#include "config.h"
#include "serial_protocol.h"

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
      _baud_switched(false),
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

bool ShaperStreamer::isAllowedBaud(uint32_t baud) {
    return proto::allowed_baud(baud);
}

uint16_t ShaperStreamer::pickRate(uint16_t requested, uint32_t baud, bool over_serial) {
    if (requested == 0) requested = SHAPER_DEFAULT_RATE_HZ;
    return proto::pick_rate(requested, baud, over_serial, sizeof(ShaperBinaryPacket), SERIAL_PAYLOAD_EFFICIENCY);
}

bool ShaperStreamer::startSession(uint8_t duration_s, uint16_t rate_hz, bool stream_to_serial,
                                  uint32_t serial_baud) {
    if (duration_s == 0) duration_s = SHAPER_DEFAULT_DURATION_S;
    if (duration_s > SHAPER_MAX_DURATION_S) duration_s = SHAPER_MAX_DURATION_S;

    uint32_t link_baud = SERIAL_DEFAULT_BAUD;
    bool switch_baud = false;
    if (stream_to_serial && serial_baud != 0 && serial_baud != SERIAL_DEFAULT_BAUD && isAllowedBaud(serial_baud)) {
        link_baud = serial_baud;
        switch_baud = true;
    }

    uint16_t picked = pickRate(rate_hz, link_baud, stream_to_serial);

    _duration_s = duration_s;
    _stream_to_serial = stream_to_serial;
    _rate_hz = picked;
    _interval_us = 1000000UL / _rate_hz;

    switch (_rate_hz) {
        case 3200: _adxl.setRate(ADXL345_SPI::RATE_3200HZ); break;
        case 1600: _adxl.setRate(ADXL345_SPI::RATE_1600HZ); break;
        case 800:  _adxl.setRate(ADXL345_SPI::RATE_800HZ);  break;
        case 400:  _adxl.setRate(ADXL345_SPI::RATE_400HZ);  break;
        default:   _adxl.setRate(ADXL345_SPI::RATE_200HZ);  break;
    }

    _sample_count = 0;
    _packet_seq = 0;
    _batch_index = 0;

    if (picked < rate_hz) {
        Serial.printf("// WARN: rate limited to %u Hz (requested %u) by the %lu baud serial link\n",
                      picked, rate_hz, (unsigned long)link_baud);
    }
    Serial.printf("// SHAPER_SESSION_STARTED: duration=%u s, rate=%u Hz, baud=%lu\n",
                  _duration_s, _rate_hz, (unsigned long)link_baud);

    if (switch_baud) {
        Serial.flush();                       // the line above must leave at the old baud
        Serial.updateBaudRate(link_baud);
        _baud_switched = true;
    }

    _session_start_ms = millis();
    _next_sample_us = micros();
    _is_running = true;
    return true;
}

void ShaperStreamer::stopSession() {
    if (!_is_running) return;

    flushBatch();
    _is_running = false;

    // Revert ADXL345 back to 200 Hz for Mode A
    _adxl.setRate(ADXL345_SPI::RATE_200HZ);

    // The leading newline terminates any partial binary packet in the host's buffer. The marker is
    // sent at the session baud (the host is still listening there) and only then is the baud
    // restored, so the host knows exactly when to switch back.
    Serial.printf("\n// SHAPER_SESSION_ENDED: collected %u samples\n", _sample_count);
    if (_baud_switched) {
        Serial.flush();
        delay(20);
        Serial.updateBaudRate(SERIAL_DEFAULT_BAUD);
        _baud_switched = false;
    }
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
