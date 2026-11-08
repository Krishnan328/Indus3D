#include "as5600.h"
#include "pico/stdlib.h"
#include <stdio.h>

#define I2C_TIMEOUT_US 1000 // 1.0ms timeout avoids blocking the 250 Hz loop

bool as5600_init_bus(i2c_inst_t *i2c, uint sda_pin, uint scl_pin, uint baudrate_hz) {
    i2c_init(i2c, baudrate_hz);
    gpio_set_function(sda_pin, GPIO_FUNC_I2C);
    gpio_set_function(scl_pin, GPIO_FUNC_I2C);
    gpio_pull_up(sda_pin);
    gpio_pull_up(scl_pin);
    return true;
}

bool as5600_read_raw(i2c_inst_t *i2c, uint8_t reg, uint8_t *buf, size_t len) {
    // nostop = true sends Repeated Start (Sr) so the AS5600 retains the target register pointer
    int res = i2c_write_timeout_us(i2c, AS5600_I2C_ADDR, &reg, 1, true, I2C_TIMEOUT_US);
    if (res != 1) return false;

    res = i2c_read_timeout_us(i2c, AS5600_I2C_ADDR, buf, len, false, I2C_TIMEOUT_US);
    return (res == (int)len);
}

bool as5600_read8(i2c_inst_t *i2c, uint8_t reg, uint8_t *val) {
    return as5600_read_raw(i2c, reg, val, 1);
}

bool as5600_read16(i2c_inst_t *i2c, uint8_t reg, uint16_t *val) {
    uint8_t raw[2];
    if (!as5600_read_raw(i2c, reg, raw, 2)) {
        return false;
    }
    *val = ((uint16_t)raw[0] << 8) | raw[1];
    return true;
}

bool as5600_write_raw(i2c_inst_t *i2c, uint8_t reg, uint8_t *buf, size_t len) {
    uint8_t tx_buf[len + 1];
    tx_buf[0] = reg;
    for (size_t i = 0; i < len; i++) {
        tx_buf[i + 1] = buf[i];
    }
    int res = i2c_write_timeout_us(i2c, AS5600_I2C_ADDR, tx_buf, len + 1, false, I2C_TIMEOUT_US);
    return (res == (int)(len + 1));
}

bool as5600_write8(i2c_inst_t *i2c, uint8_t reg, uint8_t val) {
    return as5600_write_raw(i2c, reg, &val, 1);
}

bool as5600_write16(i2c_inst_t *i2c, uint8_t reg, uint16_t val) {
    uint8_t raw[2];
    raw[0] = (val >> 8) & 0xFF;
    raw[1] = val & 0xFF;
    return as5600_write_raw(i2c, reg, raw, 2);
}

bool as5600_get_angle(i2c_inst_t *i2c, uint16_t *val) {
    uint16_t raw;
    if (!as5600_read16(i2c, AS5600_REG_ANGLE, &raw)) {
        return false;
    }
    *val = raw & 0x0FFF; // 12-bit angle
    return true;
}

bool as5600_get_raw_angle(i2c_inst_t *i2c, uint16_t *val) {
    uint16_t raw;
    if (!as5600_read16(i2c, AS5600_REG_RAW_ANGLE, &raw)) {
        return false;
    }
    *val = raw & 0x0FFF;
    return true;
}

bool as5600_get_status(i2c_inst_t *i2c, uint8_t *detected, uint8_t *too_weak, uint8_t *too_strong) {
    uint8_t status = 0;
    if (!as5600_read8(i2c, AS5600_REG_STATUS, &status)) {
        return false;
    }
    *detected   = (status & AS5600_BIT_MD) ? 1 : 0;
    *too_weak   = (status & AS5600_BIT_ML) ? 1 : 0;
    *too_strong = (status & AS5600_BIT_MH) ? 1 : 0;
    return true;
}

bool as5600_get_magnet_state(i2c_inst_t *i2c, uint8_t *state) {
    uint8_t detected = 0, too_weak = 0, too_strong = 0;
    if (!as5600_get_status(i2c, &detected, &too_weak, &too_strong)) {
        *state = MAGNET_STATE_UNKNOWN;
        return false;
    }
    if (detected) {
        if (too_weak) {
            *state = MAGNET_STATE_TOO_WEAK;
        } else if (too_strong) {
            *state = MAGNET_STATE_TOO_STRONG;
        } else {
            *state = MAGNET_STATE_DETECTED;
        }
    } else {
        *state = MAGNET_STATE_NOT_DETECTED;
    }
    return true;
}

bool as5600_get_agc(i2c_inst_t *i2c, uint8_t *val) {
    return as5600_read8(i2c, AS5600_REG_AGC, val);
}

bool as5600_get_magnitude(i2c_inst_t *i2c, uint16_t *val) {
    return as5600_read16(i2c, AS5600_REG_MAGNITUDE, val);
}

bool as5600_set_hysteresis(i2c_inst_t *i2c, uint8_t hyst) {
    uint16_t conf;
    if (!as5600_read16(i2c, AS5600_REG_CONF, &conf)) {
        return false;
    }
    conf &= ~(0x03 << 2);
    conf |= ((hyst & 0x03) << 2);
    return as5600_write16(i2c, AS5600_REG_CONF, conf);
}

bool as5600_configure_fast(i2c_inst_t *i2c) {
    // AS5600 CONF Register (14-bit):
    // Bits 12:10 (FTH)  = 001 (Fast Filter Threshold: 6 LSBs for fast step detection)
    // Bits 9:8   (SF)   = 11  (Slow Filter: 2x, fastest baseline response time)
    // Bits 3:2   (HYST) = 10  (Hysteresis: 2 LSBs noise rejection)
    // All other bits default (Watchdog 0, Power Mode NOM 00)
    // Total: (1 << 10) | (3 << 8) | (2 << 2) = 0x0400 | 0x0300 | 0x0008 = 0x0708
    return as5600_write16(i2c, AS5600_REG_CONF, 0x0708);
}

bool as5600_configure_smooth(i2c_inst_t *i2c) {
    // AS5600 CONF Register (14-bit) for Diameter Precision Sensing:
    // Bits 12:10 (FTH)  = 000 (Slow filter only, NO abrupt step snapping)
    // Bits 9:8   (SF)   = 00  (Slow Filter: 16x for maximum noise rejection <0.17 LSB RMS)
    // Bits 3:2   (HYST) = 11  (Hysteresis: 3 LSBs to suppress tiny mechanical vibrations)
    // All other bits default (Watchdog 0, Power Mode NOM 00)
    // Total: (0 << 10) | (0 << 8) | (3 << 2) = 0x000C
    return as5600_write16(i2c, AS5600_REG_CONF, 0x000C);
}

void as5600_bus_recover(i2c_inst_t *i2c, uint sda_pin, uint scl_pin, uint baudrate_hz) {
    // 1. Fully de-initialize the hardware I2C controller to clear FIFOs/aborts
    i2c_deinit(i2c);

    // 2. Switch pins temporarily to software GPIO
    gpio_set_function(sda_pin, GPIO_FUNC_SIO);
    gpio_set_function(scl_pin, GPIO_FUNC_SIO);

    gpio_set_dir(sda_pin, GPIO_IN);
    gpio_pull_up(sda_pin);

    gpio_set_dir(scl_pin, GPIO_OUT);
    gpio_put(scl_pin, 1);
    sleep_us(5);

    // 3. Pulse SCL up to 16 times to un-wedge any slave holding SDA low
    for (int i = 0; i < 16; i++) {
        if (gpio_get(sda_pin)) {
            break; // Slave released SDA high
        }
        gpio_put(scl_pin, 0);
        sleep_us(5);
        gpio_put(scl_pin, 1);
        sleep_us(5);
    }

    // 4. Generate a clean STOP condition: SDA low while SCL high, then SDA high
    gpio_set_dir(sda_pin, GPIO_OUT);
    gpio_put(sda_pin, 0);
    sleep_us(5);
    gpio_put(scl_pin, 1);
    sleep_us(5);
    gpio_put(sda_pin, 1);
    sleep_us(5);

    // 5. Restore pins to hardware I2C peripheral and re-initialize cleanly
    gpio_set_dir(sda_pin, GPIO_IN);
    gpio_pull_up(sda_pin);
    gpio_pull_up(scl_pin);
    gpio_set_function(sda_pin, GPIO_FUNC_I2C);
    gpio_set_function(scl_pin, GPIO_FUNC_I2C);

    i2c_init(i2c, baudrate_hz);
}


