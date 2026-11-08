#include "adxl345_spi.h"

ADXL345_SPI::ADXL345_SPI(uint8_t cs_pin)
    : _cs_pin(cs_pin),
      _spi_settings(1000000, MSBFIRST, SPI_MODE3) {}

bool ADXL345_SPI::begin() {
    // Set CS HIGH as output to unselect the device.
    pinMode(_cs_pin, OUTPUT);
    digitalWrite(_cs_pin, HIGH);

    // Enable internal pull-up on MISO (GPIO12 / D6) to prevent floating line
    pinMode(12, INPUT_PULLUP);

    // Initialize Hardware SPI
    SPI.begin();
    delay(10);

    // Verify Device ID
    uint8_t dev_id = getDeviceID();
    if (dev_id != EXPECTED_DEVID) {
        // Retry once after small delay
        delay(10);
        dev_id = getDeviceID();
        if (dev_id != EXPECTED_DEVID) {
            return false;
        }
    }

    // Configure Range (+-16g) and Full Resolution (13-bit, 3.90625 mg/LSB)
    setRangeAndFullRes(16);
    delay(5);

    // Default rate for real-time monitoring: 200 Hz
    setRate(RATE_200HZ);
    delay(5);

    // Configure FIFO in bypass mode for direct polling (or stream mode for burst)
    writeRegister(REG_FIFO_CTL, 0x00);
    delay(5);

    // Enable measurement mode
    setMeasureMode(true);
    delay(10);

    uint8_t pctl = readRegister(REG_POWER_CTL);
    uint8_t fmt = readRegister(REG_DATA_FORMAT);
    Serial.printf("[ADXL] Reg 0x2D (POWER_CTL)=0x%02X, Reg 0x31 (FORMAT)=0x%02X\n", pctl, fmt);

    return true;
}

uint8_t ADXL345_SPI::getDeviceID() {
    return readRegister(REG_DEVID);
}

bool ADXL345_SPI::isConnected() {
    return (getDeviceID() == EXPECTED_DEVID);
}

bool ADXL345_SPI::setRate(uint8_t rate_code) {
    writeRegister(REG_BW_RATE, rate_code & 0x0F);
    return true;
}

bool ADXL345_SPI::setRangeAndFullRes(uint8_t range_g) {
    uint8_t format_val = 0x08; // Set FULL_RES bit (D3)

    if (range_g <= 2) {
        format_val |= 0x00; // +-2g
    } else if (range_g <= 4) {
        format_val |= 0x01; // +-4g
    } else if (range_g <= 8) {
        format_val |= 0x02; // +-8g
    } else {
        format_val |= 0x03; // +-16g
    }

    writeRegister(REG_DATA_FORMAT, format_val);
    return true;
}

bool ADXL345_SPI::setMeasureMode(bool enable) {
    uint8_t val = enable ? 0x08 : 0x00; // D3 = Measure
    writeRegister(REG_POWER_CTL, val);
    return true;
}

bool ADXL345_SPI::readRaw(AccelDataRaw& raw) {
    uint8_t x0 = readRegister(REG_DATAX0);
    uint8_t x1 = readRegister(REG_DATAX0 + 1);
    uint8_t y0 = readRegister(REG_DATAX0 + 2);
    uint8_t y1 = readRegister(REG_DATAX0 + 3);
    uint8_t z0 = readRegister(REG_DATAX0 + 4);
    uint8_t z1 = readRegister(REG_DATAX0 + 5);

    raw.x = (int16_t)(x0 | (x1 << 8));
    raw.y = (int16_t)(y0 | (y1 << 8));
    raw.z = (int16_t)(z0 | (z1 << 8));

    return true;
}

bool ADXL345_SPI::readMg(AccelDataMg& mg) {
    AccelDataRaw raw;
    if (!readRaw(raw)) return false;

    mg.x = (int32_t)lroundf(raw.x * SCALE_MG_PER_LSB);
    mg.y = (int32_t)lroundf(raw.y * SCALE_MG_PER_LSB);
    mg.z = (int32_t)lroundf(raw.z * SCALE_MG_PER_LSB);

    return true;
}

bool ADXL345_SPI::readG(AccelDataG& g) {
    AccelDataRaw raw;
    if (!readRaw(raw)) return false;

    g.x = raw.x * SCALE_G_PER_LSB;
    g.y = raw.y * SCALE_G_PER_LSB;
    g.z = raw.z * SCALE_G_PER_LSB;

    return true;
}

uint8_t ADXL345_SPI::readFifoEntries() {
    uint8_t status = readRegister(REG_FIFO_STATUS);
    return (status & 0x3F); // Lower 6 bits is entry count
}

void ADXL345_SPI::writeRegister(uint8_t reg, uint8_t val) {
    uint8_t buf[2] = { (uint8_t)(reg & 0x3F), val };
    SPI.beginTransaction(_spi_settings);
    digitalWrite(_cs_pin, LOW);
    delayMicroseconds(2);
    SPI.transfer(buf, 2);
    delayMicroseconds(2);
    digitalWrite(_cs_pin, HIGH);
    SPI.endTransaction();
}

uint8_t ADXL345_SPI::readRegister(uint8_t reg) {
    uint8_t buf[2] = { (uint8_t)(0x80 | (reg & 0x3F)), 0x00 };
    SPI.beginTransaction(_spi_settings);
    digitalWrite(_cs_pin, LOW);
    delayMicroseconds(2);
    SPI.transfer(buf, 2);
    delayMicroseconds(2);
    digitalWrite(_cs_pin, HIGH);
    SPI.endTransaction();
    return buf[1];
}

void ADXL345_SPI::readRegisters(uint8_t start_reg, uint8_t* buffer, uint8_t len) {
    SPI.beginTransaction(_spi_settings);
    digitalWrite(_cs_pin, LOW);
    delayMicroseconds(1);
    SPI.transfer(0x80 | 0x40 | (start_reg & 0x3F)); // Read + Multi-byte
    for (uint8_t i = 0; i < len; ++i) {
        buffer[i] = SPI.transfer(0x00);
    }
    delayMicroseconds(1);
    digitalWrite(_cs_pin, HIGH);
    SPI.endTransaction();
}
