#ifndef AS5600_H
#define AS5600_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "hardware/i2c.h"

#define AS5600_I2C_ADDR 0x36

// Registers
#define AS5600_REG_ZMCO        0x00
#define AS5600_REG_ZPOS        0x01
#define AS5600_REG_MPOS        0x03
#define AS5600_REG_MANG        0x05
#define AS5600_REG_CONF        0x07
#define AS5600_REG_RAW_ANGLE   0x0C
#define AS5600_REG_ANGLE       0x0E
#define AS5600_REG_STATUS      0x0B
#define AS5600_REG_AGC         0x1A
#define AS5600_REG_MAGNITUDE   0x1B
#define AS5600_REG_BURN        0xFF

// Magnet Status Bits
#define AS5600_BIT_MH          0x08 // Magnet too strong (overflow)
#define AS5600_BIT_ML          0x10 // Magnet too weak (underflow)
#define AS5600_BIT_MD          0x20 // Magnet detected

// Magnet state enums matching Roadrunner/Klipper conventions
#define MAGNET_STATE_UNKNOWN        0
#define MAGNET_STATE_NOT_DETECTED   1
#define MAGNET_STATE_TOO_WEAK       2
#define MAGNET_STATE_TOO_STRONG     3
#define MAGNET_STATE_DETECTED       4

// Low-level read/write
bool as5600_read_raw(i2c_inst_t *i2c, uint8_t reg, uint8_t *buf, size_t len);
bool as5600_read8(i2c_inst_t *i2c, uint8_t reg, uint8_t *val);
bool as5600_read16(i2c_inst_t *i2c, uint8_t reg, uint16_t *val);
bool as5600_write_raw(i2c_inst_t *i2c, uint8_t reg, uint8_t *buf, size_t len);
bool as5600_write8(i2c_inst_t *i2c, uint8_t reg, uint8_t val);
bool as5600_write16(i2c_inst_t *i2c, uint8_t reg, uint16_t val);

// High-level API
bool as5600_init_bus(i2c_inst_t *i2c, uint sda_pin, uint scl_pin, uint baudrate_hz);
bool as5600_get_angle(i2c_inst_t *i2c, uint16_t *val);
bool as5600_get_raw_angle(i2c_inst_t *i2c, uint16_t *val);
bool as5600_get_status(i2c_inst_t *i2c, uint8_t *detected, uint8_t *too_weak, uint8_t *too_strong);
bool as5600_get_magnet_state(i2c_inst_t *i2c, uint8_t *state);
bool as5600_get_agc(i2c_inst_t *i2c, uint8_t *val);
bool as5600_get_magnitude(i2c_inst_t *i2c, uint16_t *val);
bool as5600_set_hysteresis(i2c_inst_t *i2c, uint8_t hyst);
bool as5600_configure_fast(i2c_inst_t *i2c);
bool as5600_configure_smooth(i2c_inst_t *i2c);
void as5600_bus_recover(i2c_inst_t *i2c, uint sda_pin, uint scl_pin, uint baudrate_hz);

#endif // AS5600_H
