#include "adxl345.h"
#include "pico/stdlib.h"
#include <stdio.h>

// Internal register helpers
static void adxl345_cs_select(uint cs_pin) {
    asm volatile("nop \n nop \n nop");
    gpio_put(cs_pin, 0);
    asm volatile("nop \n nop \n nop");
}

static void adxl345_cs_deselect(uint cs_pin) {
    asm volatile("nop \n nop \n nop");
    gpio_put(cs_pin, 1);
    asm volatile("nop \n nop \n nop");
}

static void adxl345_write_reg(spi_inst_t *spi, uint cs_pin, uint8_t reg, uint8_t val) {
    uint8_t buf[2];
    buf[0] = reg & 0x3F; // Bit 7=0 (write), Bit 6=0 (single-byte)
    buf[1] = val;

    adxl345_cs_select(cs_pin);
    spi_write_blocking(spi, buf, 2);
    adxl345_cs_deselect(cs_pin);
}

static uint8_t adxl345_read_reg(spi_inst_t *spi, uint cs_pin, uint8_t reg) {
    uint8_t cmd = 0x80 | (reg & 0x3F); // Bit 7=1 (read), Bit 6=0 (single-byte)
    uint8_t val = 0;

    adxl345_cs_select(cs_pin);
    spi_write_blocking(spi, &cmd, 1);
    spi_read_blocking(spi, 0x00, &val, 1);
    adxl345_cs_deselect(cs_pin);

    return val;
}

bool adxl345_check_id(spi_inst_t *spi, uint cs_pin) {
    uint8_t id = adxl345_read_reg(spi, cs_pin, ADXL345_REG_DEVID);
    return (id == ADXL345_DEVID_VALUE);
}

bool adxl345_init(spi_inst_t *spi, uint sck_pin, uint mosi_pin, uint miso_pin, uint cs_pin, uint baudrate_hz) {
    // 1. Initialize SPI Peripheral (Mode 3: CPOL=1, CPHA=1 is native for ADXL345)
    spi_init(spi, baudrate_hz);
    spi_set_format(spi, 8, SPI_CPOL_1, SPI_CPHA_1, SPI_MSB_FIRST);

    // 2. Configure GPIO Functions
    gpio_set_function(sck_pin, GPIO_FUNC_SPI);
    gpio_set_function(mosi_pin, GPIO_FUNC_SPI);
    gpio_set_function(miso_pin, GPIO_FUNC_SPI);

    // Enable internal pull-up on MISO to prevent floating over long wire
    gpio_pull_up(miso_pin);

    // 3. Configure Chip Select (Active Low)
    gpio_init(cs_pin);
    gpio_set_dir(cs_pin, GPIO_OUT);
    gpio_put(cs_pin, 1);

    sleep_ms(10);

    // 4. Verify Sensor Communication
    if (!adxl345_check_id(spi, cs_pin)) {
        // Retry once in case of bus settle
        sleep_ms(20);
        if (!adxl345_check_id(spi, cs_pin)) {
            return false;
        }
    }

    // 5. Configure ADXL345:
    // Rate: 400 Hz output data rate (ODR), 200 Hz bandwidth (clean 250 Hz loop sync)
    adxl345_write_reg(spi, cs_pin, ADXL345_REG_BW_RATE, 0x0C);

    // Data Format: Full Resolution (+-16g range, ~3.9 mg/LSB)
    adxl345_write_reg(spi, cs_pin, ADXL345_REG_DATA_FORMAT, 0x0B);

    // FIFO: Bypass mode (continuous live sampling)
    adxl345_write_reg(spi, cs_pin, ADXL345_REG_FIFO_CTL, 0x00);

    // Power Control: Set Measurement Mode
    adxl345_write_reg(spi, cs_pin, ADXL345_REG_POWER_CTL, 0x08);

    sleep_ms(10);
    return true;
}

bool adxl345_read_accel_raw(spi_inst_t *spi, uint cs_pin, int16_t *x, int16_t *y, int16_t *z) {
    // Burst read of 6 registers starting at DATAX0 (0x32):
    // Bit 7=1 (read), Bit 6=1 (multi-byte burst) -> 0xC0 | 0x32 = 0xF2
    uint8_t cmd = 0xC0 | ADXL345_REG_DATAX0;
    uint8_t raw[6] = {0};

    adxl345_cs_select(cs_pin);
    spi_write_blocking(spi, &cmd, 1);
    int read_bytes = spi_read_blocking(spi, 0x00, raw, 6);
    adxl345_cs_deselect(cs_pin);

    if (read_bytes != 6) {
        return false;
    }

    *x = (int16_t)((uint16_t)raw[0] | ((uint16_t)raw[1] << 8));
    *y = (int16_t)((uint16_t)raw[2] | ((uint16_t)raw[3] << 8));
    *z = (int16_t)((uint16_t)raw[4] | ((uint16_t)raw[5] << 8));

    return true;
}

bool adxl345_read_accel_mg(spi_inst_t *spi, uint cs_pin, int16_t *x_mg, int16_t *y_mg, int16_t *z_mg) {
    int16_t rx = 0, ry = 0, rz = 0;
    if (!adxl345_read_accel_raw(spi, cs_pin, &rx, &ry, &rz)) {
        return false;
    }

    // Convert raw counts to milligravities (mg): 3.90625 mg per LSB in full resolution
    *x_mg = (int16_t)((float)rx * ADXL345_MG_PER_LSB);
    *y_mg = (int16_t)((float)ry * ADXL345_MG_PER_LSB);
    *z_mg = (int16_t)((float)rz * ADXL345_MG_PER_LSB);

    return true;
}
