#pragma once

#include <Arduino.h>
#include <Wire.h>

struct ChamberTelemetry {
    float temperature_c;
    float humidity_pct;
    float pressure_hpa;
    bool is_valid;
    uint32_t last_sample_ms;
};

class BME280_I2C {
public:
    BME280_I2C(uint8_t sda_pin = 4, uint8_t scl_pin = 5);

    bool begin(uint8_t address = 0); // 0 = auto-scan 0x76 then 0x77
    bool isConnected() const { return _is_initialized; }
    uint8_t getAddress() const { return _address; }
    uint8_t getChipID() const { return _chip_id; }
    bool isBME() const { return _chip_id == CHIP_ID_BME280; }

    bool read(ChamberTelemetry& telemetry);

    static constexpr uint8_t CHIP_ID_BME280 = 0x60;
    static constexpr uint8_t CHIP_ID_BMP280 = 0x58;

private:
    uint8_t _sda_pin;
    uint8_t _scl_pin;
    uint8_t _address;
    uint8_t _chip_id;
    bool _is_initialized;
    int32_t _t_fine;

    // Calibration data
    struct {
        uint16_t dig_T1;
        int16_t  dig_T2;
        int16_t  dig_T3;

        uint16_t dig_P1;
        int16_t  dig_P2;
        int16_t  dig_P3;
        int16_t  dig_P4;
        int16_t  dig_P5;
        int16_t  dig_P6;
        int16_t  dig_P7;
        int16_t  dig_P8;
        int16_t  dig_P9;

        uint8_t  dig_H1;
        int16_t  dig_H2;
        uint8_t  dig_H3;
        int16_t  dig_H4;
        int16_t  dig_H5;
        int8_t   dig_H6;
    } _calib;

    bool readCalibrationData();
    void writeRegister(uint8_t reg, uint8_t val);
    uint8_t readRegister(uint8_t reg);
    bool readRegisters(uint8_t start_reg, uint8_t* buffer, uint8_t len);

    float compensateTemperature(int32_t raw_t);
    float compensatePressure(int32_t raw_p);
    float compensateHumidity(int32_t raw_h);
};
