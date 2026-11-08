#pragma once

#include <Arduino.h>
#include <SPI.h>

struct AccelDataRaw {
    int16_t x;
    int16_t y;
    int16_t z;
};

struct AccelDataMg {
    int32_t x;
    int32_t y;
    int32_t z;
};

struct AccelDataG {
    float x;
    float y;
    float z;
};

class ADXL345_SPI {
public:
    ADXL345_SPI(uint8_t cs_pin);

    // Initialization and Self-Test
    bool begin();
    uint8_t getDeviceID();
    bool isConnected();

    // Configuration
    bool setRate(uint8_t rate_code); // e.g. 0x0B for 200 Hz, 0x0E for 1600 Hz, 0x0F for 3200 Hz
    bool setRangeAndFullRes(uint8_t range_g = 16); // Default +-16g full resolution (3.90625 mg/LSB)
    bool setMeasureMode(bool enable = true);

    // High-speed Reading
    bool readRaw(AccelDataRaw& raw);
    bool readMg(AccelDataMg& mg);
    bool readG(AccelDataG& g);

    // Multi-sample burst read from FIFO
    uint8_t readFifoEntries();

    // Constant conversion factor for Full-Resolution Mode
    static constexpr float SCALE_MG_PER_LSB = 3.90625f;
    static constexpr float SCALE_G_PER_LSB  = 0.00390625f;

    // Register Definitions
    static constexpr uint8_t REG_DEVID          = 0x00;
    static constexpr uint8_t REG_THRESH_TAP     = 0x1D;
    static constexpr uint8_t REG_OFSX           = 0x1E;
    static constexpr uint8_t REG_OFSY           = 0x1F;
    static constexpr uint8_t REG_OFSZ           = 0x20;
    static constexpr uint8_t REG_BW_RATE        = 0x2C;
    static constexpr uint8_t REG_POWER_CTL      = 0x2D;
    static constexpr uint8_t REG_INT_ENABLE     = 0x2E;
    static constexpr uint8_t REG_INT_MAP        = 0x2F;
    static constexpr uint8_t REG_INT_SOURCE     = 0x30;
    static constexpr uint8_t REG_DATA_FORMAT    = 0x31;
    static constexpr uint8_t REG_DATAX0         = 0x32;
    static constexpr uint8_t REG_FIFO_CTL       = 0x38;
    static constexpr uint8_t REG_FIFO_STATUS    = 0x39;

    // Rate Constants (BW_RATE)
    static constexpr uint8_t RATE_100HZ  = 0x0A;
    static constexpr uint8_t RATE_200HZ  = 0x0B;
    static constexpr uint8_t RATE_400HZ  = 0x0C;
    static constexpr uint8_t RATE_800HZ  = 0x0D;
    static constexpr uint8_t RATE_1600HZ = 0x0E;
    static constexpr uint8_t RATE_3200HZ = 0x0F;

    static constexpr uint8_t EXPECTED_DEVID = 0xE5;

private:
    uint8_t _cs_pin;
    SPISettings _spi_settings;

    void writeRegister(uint8_t reg, uint8_t val);
    uint8_t readRegister(uint8_t reg);
    void readRegisters(uint8_t start_reg, uint8_t* buffer, uint8_t len);
};
