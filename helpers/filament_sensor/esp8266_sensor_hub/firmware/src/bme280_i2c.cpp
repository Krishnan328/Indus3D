#include "bme280_i2c.h"

BME280_I2C::BME280_I2C(uint8_t sda_pin, uint8_t scl_pin)
    : _sda_pin(sda_pin),
      _scl_pin(scl_pin),
      _address(0),
      _chip_id(0),
      _is_initialized(false),
      _t_fine(0) {
    memset(&_calib, 0, sizeof(_calib));
}

bool BME280_I2C::begin(uint8_t address) {
    pinMode(_sda_pin, INPUT_PULLUP);
    pinMode(_scl_pin, INPUT_PULLUP);
    Wire.begin(_sda_pin, _scl_pin);
    Wire.setClock(100000); // 100 kHz standard I2C
    delay(20);

    // Scan I2C bus for visibility
    Serial.println();
    Serial.printf("[I2C] Scanning bus on SDA=GPIO%d (D2), SCL=GPIO%d (D1)...\n", _sda_pin, _scl_pin);
    uint8_t count = 0;
    for (uint8_t a = 1; a < 127; ++a) {
        Wire.beginTransmission(a);
        if (Wire.endTransmission() == 0) {
            Serial.printf("[I2C] -> Device responded at address 0x%02X\n", a);
            count++;
        }
    }
    if (count == 0) {
        Serial.println("[I2C] -> No devices on D2(SDA)/D1(SCL). Testing swapped pins D1(SDA)/D2(SCL)...");
        Wire.begin(_scl_pin, _sda_pin);
        delay(20);
        uint8_t swap_count = 0;
        for (uint8_t a = 1; a < 127; ++a) {
            Wire.beginTransmission(a);
            if (Wire.endTransmission() == 0) {
                Serial.printf("[I2C] -> Device found on SWAPPED pins at address 0x%02X!\n", a);
                swap_count++;
            }
        }
        if (swap_count > 0) {
            uint8_t tmp = _sda_pin;
            _sda_pin = _scl_pin;
            _scl_pin = tmp;
            count = swap_count;
            Serial.println("[I2C] Auto-swapped SDA and SCL pins successfully.");
        } else {
            Wire.begin(_sda_pin, _scl_pin);
            Serial.println("[I2C] -> No I2C devices responded on either pin combination.");
            Serial.println("       Please verify BME280 VCC (3.3V), GND, SDA (D2), SCL (D1) connections.");
        }
    }

    uint8_t target_addrs[2] = {0x76, 0x77};
    uint8_t addr_count = 2;

    if (address != 0) {
        target_addrs[0] = address;
        addr_count = 1;
    }

    bool found = false;
    for (uint8_t i = 0; i < addr_count; ++i) {
        _address = target_addrs[i];
        _chip_id = readRegister(0xD0);
        if (_chip_id == CHIP_ID_BME280 || _chip_id == CHIP_ID_BMP280) {
            found = true;
            break;
        }
    }

    if (!found) {
        _address = 0;
        _is_initialized = false;
        return false;
    }

    // Soft reset device
    writeRegister(0xE0, 0xB6);
    delay(20);

    // Read factory calibration registers
    if (!readCalibrationData()) {
        _is_initialized = false;
        return false;
    }

    // Configure humidity oversampling = 1x (only affects BME280)
    if (_chip_id == CHIP_ID_BME280) {
        writeRegister(0xF2, 0x01);
    }

    // Configure config register: standby 500ms, filter coeff 4
    writeRegister(0xF5, (0x04 << 5) | (0x02 << 2));

    // Configure ctrl_meas: temp oversample 1x, press oversample 1x, Normal mode
    writeRegister(0xF4, (0x01 << 5) | (0x01 << 2) | 0x03);

    _is_initialized = true;
    return true;
}

bool BME280_I2C::readCalibrationData() {
    uint8_t buf[24];

    // Read Dig_T and Dig_P (0x88 to 0x9F -> 24 bytes)
    if (!readRegisters(0x88, buf, 24)) return false;

    _calib.dig_T1 = (uint16_t)(buf[0] | (buf[1] << 8));
    _calib.dig_T2 = (int16_t)(buf[2] | (buf[3] << 8));
    _calib.dig_T3 = (int16_t)(buf[4] | (buf[5] << 8));

    _calib.dig_P1 = (uint16_t)(buf[6] | (buf[7] << 8));
    _calib.dig_P2 = (int16_t)(buf[8] | (buf[9] << 8));
    _calib.dig_P3 = (int16_t)(buf[10] | (buf[11] << 8));
    _calib.dig_P4 = (int16_t)(buf[12] | (buf[13] << 8));
    _calib.dig_P5 = (int16_t)(buf[14] | (buf[15] << 8));
    _calib.dig_P6 = (int16_t)(buf[16] | (buf[17] << 8));
    _calib.dig_P7 = (int16_t)(buf[18] | (buf[19] << 8));
    _calib.dig_P8 = (int16_t)(buf[20] | (buf[21] << 8));
    _calib.dig_P9 = (int16_t)(buf[22] | (buf[23] << 8));

    // Read Dig_H1 (0xA1 -> 1 byte)
    _calib.dig_H1 = readRegister(0xA1);

    // Read Dig_H2 to Dig_H6 (0xE1 to 0xE7 -> 7 bytes)
    uint8_t h_buf[7];
    if (readRegisters(0xE1, h_buf, 7)) {
        _calib.dig_H2 = (int16_t)(h_buf[0] | (h_buf[1] << 8));
        _calib.dig_H3 = h_buf[2];
        _calib.dig_H4 = (int16_t)(((int8_t)h_buf[3] << 4) | (h_buf[4] & 0x0F));
        _calib.dig_H5 = (int16_t)(((int8_t)h_buf[5] << 4) | (h_buf[4] >> 4));
        _calib.dig_H6 = (int8_t)h_buf[6];
    }

    return true;
}

bool BME280_I2C::read(ChamberTelemetry& telemetry) {
    if (!_is_initialized) return false;

    // Read 8 bytes: press (3 bytes), temp (3 bytes), hum (2 bytes)
    uint8_t buf[8];
    if (!readRegisters(0xF7, buf, 8)) {
        telemetry.is_valid = false;
        return false;
    }

    int32_t raw_p = ((int32_t)buf[0] << 12) | ((int32_t)buf[1] << 4) | ((int32_t)buf[2] >> 4);
    int32_t raw_t = ((int32_t)buf[3] << 12) | ((int32_t)buf[4] << 4) | ((int32_t)buf[5] >> 4);
    int32_t raw_h = ((int32_t)buf[6] << 8) | (int32_t)buf[7];

    telemetry.temperature_c = compensateTemperature(raw_t);
    telemetry.pressure_hpa  = compensatePressure(raw_p);
    telemetry.humidity_pct  = compensateHumidity(raw_h);
    telemetry.is_valid      = true;
    telemetry.last_sample_ms = millis();

    return true;
}

float BME280_I2C::compensateTemperature(int32_t raw_t) {
    int32_t var1 = ((((raw_t >> 3) - ((int32_t)_calib.dig_T1 << 1))) * ((int32_t)_calib.dig_T2)) >> 11;
    int32_t var2 = (((((raw_t >> 4) - ((int32_t)_calib.dig_T1)) * ((raw_t >> 4) - ((int32_t)_calib.dig_T1))) >> 12) * ((int32_t)_calib.dig_T3)) >> 14;
    _t_fine = var1 + var2;
    int32_t T = (_t_fine * 5 + 128) >> 8;
    return (float)T / 100.0f;
}

float BME280_I2C::compensatePressure(int32_t raw_p) {
    int64_t var1 = ((int64_t)_t_fine) - 128000;
    int64_t var2 = var1 * var1 * (int64_t)_calib.dig_P6;
    var2 = var2 + ((var1 * (int64_t)_calib.dig_P5) << 17);
    var2 = var2 + (((int64_t)_calib.dig_P4) << 35);
    var1 = ((var1 * var1 * (int64_t)_calib.dig_P3) >> 8) + ((var1 * (int64_t)_calib.dig_P2) << 12);
    var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)_calib.dig_P1) >> 33;

    if (var1 == 0) return 0.0f;

    int64_t p = 1048576 - raw_p;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = (((int64_t)_calib.dig_P9) * (p >> 13) * (p >> 13)) >> 25;
    var2 = (((int64_t)_calib.dig_P8) * p) >> 19;
    p = ((p + var1 + var2) >> 8) + (((int64_t)_calib.dig_P7) << 4);

    float p_pa = (float)p / 256.0f;
    return p_pa / 100.0f; // Return in hPa
}

float BME280_I2C::compensateHumidity(int32_t raw_h) {
    if (_chip_id != CHIP_ID_BME280) return 0.0f;

    int32_t v_x1_u32r = (_t_fine - ((int32_t)76800));
    v_x1_u32r = (((((raw_h << 14) - (((int32_t)_calib.dig_H4) << 20) - (((int32_t)_calib.dig_H5) * v_x1_u32r)) +
                  ((int32_t)16384)) >> 15) *
                 (((((((v_x1_u32r * ((int32_t)_calib.dig_H6)) >> 10) *
                     (((v_x1_u32r * ((int32_t)_calib.dig_H3)) >> 11) + ((int32_t)32768))) >> 10) +
                    ((int32_t)2097152)) * ((int32_t)_calib.dig_H2) + 8192) >> 14));

    v_x1_u32r = (v_x1_u32r - (((((v_x1_u32r >> 15) * (v_x1_u32r >> 15)) >> 7) * ((int32_t)_calib.dig_H1)) >> 4));
    if (v_x1_u32r < 0) v_x1_u32r = 0;
    if (v_x1_u32r > 419430400) v_x1_u32r = 419430400;

    return (float)(v_x1_u32r >> 12) / 1024.0f;
}

void BME280_I2C::writeRegister(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(_address);
    Wire.write(reg);
    Wire.write(val);
    Wire.endTransmission();
}

uint8_t BME280_I2C::readRegister(uint8_t reg) {
    Wire.beginTransmission(_address);
    Wire.write(reg);
    Wire.endTransmission();
    Wire.requestFrom(_address, (uint8_t)1);
    if (Wire.available()) {
        return Wire.read();
    }
    return 0;
}

bool BME280_I2C::readRegisters(uint8_t start_reg, uint8_t* buffer, uint8_t len) {
    Wire.beginTransmission(_address);
    Wire.write(start_reg);
    if (Wire.endTransmission() != 0) return false;

    uint8_t bytes_received = Wire.requestFrom(_address, len);
    if (bytes_received != len) return false;

    for (uint8_t i = 0; i < len; ++i) {
        buffer[i] = Wire.read();
    }
    return true;
}
