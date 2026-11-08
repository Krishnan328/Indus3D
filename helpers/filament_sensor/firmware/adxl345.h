#ifndef ADXL345_H
#define ADXL345_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "hardware/spi.h"
#include "hardware/gpio.h"

// ADXL345 Registers
#define ADXL345_REG_DEVID          0x00
#define ADXL345_REG_THRESH_TAP     0x1D
#define ADXL345_REG_OFSX           0x1E
#define ADXL345_REG_OFSY           0x1F
#define ADXL345_REG_OFSZ           0x20
#define ADXL345_REG_DUR            0x21
#define ADXL345_REG_LATENT         0x22
#define ADXL345_REG_WINDOW         0x23
#define ADXL345_REG_THRESH_ACT     0x24
#define ADXL345_REG_THRESH_INACT   0x25
#define ADXL345_REG_TIME_INACT     0x26
#define ADXL345_REG_ACT_INACT_CTL  0x27
#define ADXL345_REG_THRESH_FF      0x28
#define ADXL345_REG_TIME_FF        0x29
#define ADXL345_REG_TAP_AXES       0x2A
#define ADXL345_REG_ACT_TAP_STATUS 0x2B
#define ADXL345_REG_BW_RATE        0x2C
#define ADXL345_REG_POWER_CTL      0x2D
#define ADXL345_REG_INT_ENABLE     0x2E
#define ADXL345_REG_INT_MAP        0x2F
#define ADXL345_REG_INT_SOURCE     0x30
#define ADXL345_REG_DATA_FORMAT    0x31
#define ADXL345_REG_DATAX0         0x32
#define ADXL345_REG_FIFO_CTL       0x38
#define ADXL345_REG_FIFO_STATUS    0x39

#define ADXL345_DEVID_VALUE        0xE5

// Scale factor: In full resolution mode, sensitivity is 3.9 mg/LSB (roughly 4 mg/LSB) across all ranges
#define ADXL345_MG_PER_LSB         3.90625f

// High-level API
bool adxl345_init(spi_inst_t *spi, uint sck_pin, uint mosi_pin, uint miso_pin, uint cs_pin, uint baudrate_hz);
bool adxl345_check_id(spi_inst_t *spi, uint cs_pin);
bool adxl345_read_accel_raw(spi_inst_t *spi, uint cs_pin, int16_t *x, int16_t *y, int16_t *z);
bool adxl345_read_accel_mg(spi_inst_t *spi, uint cs_pin, int16_t *x_mg, int16_t *y_mg, int16_t *z_mg);

#endif // ADXL345_H
