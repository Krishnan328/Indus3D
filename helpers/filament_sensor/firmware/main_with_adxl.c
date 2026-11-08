/**
 * Smart Filament Sensor Firmware with Bed ADXL345 Telemetry
 * For Raspberry Pi Pico / RP2040
 * 
 * Sensor 1 (Motion):       I2C0 on GP4 (SDA) / GP5 (SCL)
 * Sensor 2 (Diameter):     I2C1 on GP2 (SDA) / GP3 (SCL)
 * Optional Runout Pin:     GP6 (Active Low, internal pull-up)
 * 
 * Bed Accelerometer:       SPI0 on GP18 (SCK) / GP19 (MOSI) / GP16 (MISO) / GP17 (CS)
 * Clock Speed:             1.0 MHz (Optimized for 32-inch cable signal integrity)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "pico/stdlib.h"
#include "hardware/timer.h"
#include "hardware/sync.h"
#include "hardware/flash.h"
#include "hardware/spi.h"
#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include "as5600.h"
#include "adxl345.h"

// -----------------------------------------------------------------------------
// Pin Definitions
// -----------------------------------------------------------------------------
#define DIAMETER_I2C_INST       i2c1
#define DIAMETER_SDA_PIN        2
#define DIAMETER_SCL_PIN        3

#define MOTION_I2C_INST         i2c0
#define MOTION_SDA_PIN          4
#define MOTION_SCL_PIN          5

#define FILAMENT_RUNOUT_PIN     6 // Active low switch

// Bed ADXL345 SPI Pinout
#define BED_SPI_INST            spi0
#define BED_SPI_SCK_PIN         18
#define BED_SPI_MOSI_PIN        19
#define BED_SPI_MISO_PIN        16
#define BED_SPI_CS_PIN          17

// 1.0 MHz SPI clock guarantees safe transitions and negligible reflections over 32 inches
#define BED_SPI_BAUDRATE_HZ     1000000 

// Crash / Shock Threshold: >2000 mg (2.0g) sudden delta in 4 ms indicates a nozzle strike or bed collision
#define BED_CRASH_JERK_THRESHOLD_MG  2000 

#define UPDATE_INTERVAL_US      4000 // 4 ms (250 Hz main loop)

// -----------------------------------------------------------------------------
// Mechanical & Geometric Calibration Parameters
// -----------------------------------------------------------------------------
// 1. Motion Module: Bondtech BMG Extruder Gear Set
static float bmg_circumference_um       = 25273.0f;                                      // 25.273 mm per 360 deg
#define BMG_UM_PER_COUNT                (bmg_circumference_um / 4096.0f)                 // ~6.1702 um/count (162.07 counts/mm)
#define MOTION_DIRECTION_SIGN           (-1)                                             // Inverted: forward filament feed increases distance

// 2. Diameter Module: Modified Infidel (10 mm Bearings)
#define NOMINAL_FILAMENT_DIAMETER_UM    1750
#define DEFLECTION_DEG_PER_1750UM       14.5314f
#define DEFAULT_DIAMETER_DEFLECTION_SIGN (-1.0f)
#define DEFAULT_DIA_ZERO_ANGLE          (3080.0f) // Resting angle of empty bearings (hardware calibrated)
#define DEFAULT_DIA_UM_PER_COUNT        (9.4118f) // 1.76 mm / 187 counts deflection (hardware calibrated)

// Fault Bitmasks
#define FAULT_OK                        0x00
#define FAULT_MOTION_STALL              0x01 // Diameter ripple active but motion wheel stationary
#define FAULT_MOTION_REVERSE            0x02 // Filament retracting / moving backwards
#define FAULT_DIAMETER_OUT_OF_RANGE     0x04 // Diameter < 1.40 mm or > 2.10 mm
#define FAULT_RUNOUT                    0x08 // Filament absent or magnet lost
#define FAULT_BED_CRASH                 0x10 // Sudden abnormal jerk / collision on bed

// -----------------------------------------------------------------------------
// Protocol Command Codes
// -----------------------------------------------------------------------------
#define CMD_PREFIX              0xF5
#define CMD_READ_ALL            0x10
#define CMD_RESET_MOTION        0x20
#define CMD_TARE_DIAMETER       0x21
#define CMD_TARE_EMPTY          0x22
#define CMD_CAL_SPAN            0x23
#define CMD_SAVE_CONFIG         0x24
#define RESP_HEADER_1           0x05
#define RESP_HEADER_2           0xFF

// Sensor state struct (packed for binary serial transmission - 38 bytes payload)
struct __attribute__((packed)) sensor_state_t {
    uint8_t  motion_magnet_state;      // MAGNET_STATE_... (1: NOT_DETECTED, 4: DETECTED)
    uint8_t  diameter_magnet_state;    // MAGNET_STATE_... (1: NOT_DETECTED, 4: DETECTED)
    uint8_t  filament_present;         // 1: present, 0: runout
    uint8_t  fault_flags;              // FAULT_... bitmask

    int32_t  motion_full_turns;        // Full 360-deg rotations
    int32_t  motion_angle;             // Current 0-4095 angle
    int32_t  total_motion_counts;      // Continuous signed encoder count accumulator
    int32_t  total_motion_um;          // Continuous signed linear distance in micrometers
    int16_t  motion_velocity_um_s;     // Instantaneous velocity in um/s (1000 um/s = 1 mm/s)

    int32_t  diameter_raw_angle;       // Raw AS5600 0-4095 angle
    int16_t  diameter_filtered_um;     // Calibrated diameter in micrometers (+-10 um = +-0.01 mm)
    int16_t  diameter_variance_um;     // Dynamic AC ripple in micrometers

    // --- Bed ADXL345 Real-time Telemetry (8 bytes) ---
    int16_t  bed_accel_x_mg;           // Acceleration in mg (1000 mg = 1.0g)
    int16_t  bed_accel_y_mg;
    int16_t  bed_accel_z_mg;
    int16_t  bed_peak_jerk;            // Instantaneous jerk magnitude: |delta a| in mg per 4ms
} state;

// -----------------------------------------------------------------------------
// Internal Variables & Filters
// -----------------------------------------------------------------------------
static uint64_t last_update_time = 0;
static bool     debug_stream_enabled = false;

static uint16_t prev_motion_angle = 0;
static bool     motion_initialized = false;
static float    filtered_velocity_um_s = 0.0f;

static float    filtered_dia_angle = DEFAULT_DIA_ZERO_ANGLE;
static float    filtered_dia_ripple = 0.0f;
static float    dia_zero_angle = DEFAULT_DIA_ZERO_ANGLE;        // Empty bearings reference angle
static float    dia_deflection_sign = DEFAULT_DIAMETER_DEFLECTION_SIGN; // -1.0f
static float    dia_um_per_count = DEFAULT_DIA_UM_PER_COUNT;    // Calibrated scale factor (~1.75 mm / 157 counts)
static bool     diameter_initialized = false;
static uint32_t stall_timer_ms = 0;

// ADXL345 internal tracking
static bool     adxl_initialized = false;
static int16_t  prev_accel_x = 0;
static int16_t  prev_accel_y = 0;
static int16_t  prev_accel_z = 0;
static uint32_t crash_decay_counter = 0;

// -----------------------------------------------------------------------------
// Flash Non-Volatile Persistence (Last 4KB sector of Flash)
// -----------------------------------------------------------------------------
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES   (2 * 1024 * 1024)
#endif
#define FLASH_CONFIG_OFFSET     (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR       (XIP_BASE + FLASH_CONFIG_OFFSET)
#define CONFIG_MAGIC            0x46494C31 // "FIL1"
#define CONFIG_VERSION          3

struct __attribute__((packed)) sensor_config_t {
    uint32_t magic;               // CONFIG_MAGIC
    uint16_t version;             // CONFIG_VERSION
    uint16_t checksum;            // 16-bit additive checksum
    float    dia_zero_angle;      // Calibrated empty bearing angle (0.000 mm)
    float    dia_um_per_count;    // Calibrated diameter scale factor
    float    bmg_circumference_um;// Calibrated BMG gear circumference
    int8_t   motion_dir_sign;     // Inverted or standard (-1 or +1)
    int8_t   dia_deflection_sign; // Deflection sign: +1 (angle increases with filament) or -1 (angle decreases)
    uint8_t  padding[234];        // Pad to exactly 256 bytes (FLASH_PAGE_SIZE)
};

static uint16_t calc_config_checksum(const struct sensor_config_t *cfg) {
    const uint8_t *p = (const uint8_t *)cfg;
    uint16_t sum = 0;
    for (size_t i = 8; i < sizeof(struct sensor_config_t); i++) {
        sum = (sum + p[i]) & 0xFFFF;
    }
    return sum;
}

static bool config_load_from_flash(void) {
    const struct sensor_config_t *saved = (const struct sensor_config_t *)FLASH_CONFIG_ADDR;
    if (saved->magic != CONFIG_MAGIC || saved->version != CONFIG_VERSION) {
        return false;
    }
    if (saved->checksum != calc_config_checksum(saved)) {
        return false;
    }
    if (saved->dia_zero_angle < 50.0f || saved->dia_zero_angle > 4050.0f) {
        return false;
    }
    if (saved->dia_um_per_count < 2.0f || saved->dia_um_per_count > 150.0f) {
        return false;
    }
    if (saved->bmg_circumference_um < 10000.0f || saved->bmg_circumference_um > 50000.0f) {
        return false;
    }

    dia_zero_angle = saved->dia_zero_angle;
    dia_um_per_count = saved->dia_um_per_count;
    bmg_circumference_um = saved->bmg_circumference_um;
    if (saved->dia_deflection_sign == 1 || saved->dia_deflection_sign == -1) {
        dia_deflection_sign = (float)saved->dia_deflection_sign;
    }
    return true;
}

static bool config_save_to_flash(void) {
    struct sensor_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.magic = CONFIG_MAGIC;
    cfg.version = CONFIG_VERSION;
    cfg.dia_zero_angle = dia_zero_angle;
    cfg.dia_um_per_count = dia_um_per_count;
    cfg.bmg_circumference_um = bmg_circumference_um;
    cfg.motion_dir_sign = MOTION_DIRECTION_SIGN;
    cfg.dia_deflection_sign = (int8_t)(dia_deflection_sign >= 0.0f ? 1 : -1);
    cfg.checksum = calc_config_checksum(&cfg);

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, (const uint8_t *)&cfg, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
    return true;
}

static void jump_to_bootloader(void) {
    // Disable watchdog before jumping to bootloader
    watchdog_hw->ctrl = 0;
    // Direct ROM BOOTSEL jump
    reset_usb_boot(0, 0);
}

// -----------------------------------------------------------------------------
// Sensor Update Logic (Executed at 250 Hz / 4 ms)
// -----------------------------------------------------------------------------
static void update_sensors(void) {
    state.fault_flags = FAULT_OK;

    // 1. Periodic Magnet Health Check (10 Hz = every 100 ms / 25 samples at 250 Hz)
    static uint32_t health_div = 0;
    static bool motion_magnet_valid = true;
    static bool dia_magnet_valid = true;

    if (++health_div >= 25) {
        health_div = 0;

        // Check Motion Magnet
        uint8_t m_det = 0, m_weak = 0, m_strong = 0;
        bool has_m_status = as5600_get_status(MOTION_I2C_INST, &m_det, &m_weak, &m_strong);
        uint16_t m_mag = 0;
        bool has_m_mag = as5600_get_magnitude(MOTION_I2C_INST, &m_mag);

        if (has_m_mag) {
            if (m_mag >= 100) {
                motion_magnet_valid = true;
                state.motion_magnet_state = (has_m_status && m_strong) ? MAGNET_STATE_TOO_STRONG : MAGNET_STATE_DETECTED;
            } else {
                motion_magnet_valid = false;
                state.motion_magnet_state = MAGNET_STATE_NOT_DETECTED;
            }
        } else {
            motion_magnet_valid = false;
            state.motion_magnet_state = MAGNET_STATE_NOT_DETECTED;
        }

        // Check Diameter Magnet
        uint8_t d_det = 0, d_weak = 0, d_strong = 0;
        bool has_d_status = as5600_get_status(DIAMETER_I2C_INST, &d_det, &d_weak, &d_strong);
        uint16_t d_mag = 0;
        bool has_d_mag = as5600_get_magnitude(DIAMETER_I2C_INST, &d_mag);

        if (has_d_mag) {
            if (d_mag >= 100) {
                dia_magnet_valid = true;
                state.diameter_magnet_state = (has_d_status && d_strong) ? MAGNET_STATE_TOO_STRONG : MAGNET_STATE_DETECTED;
            } else {
                dia_magnet_valid = false;
                state.diameter_magnet_state = MAGNET_STATE_NOT_DETECTED;
            }
        } else {
            dia_magnet_valid = false;
            state.diameter_magnet_state = MAGNET_STATE_NOT_DETECTED;
        }
    }

    // 2. Motion Module (BMG Extruder Gear - 250 Hz sampling)
    static uint32_t motion_err_count = 0;
    uint16_t current_motion_angle = 0;
    bool motion_read_ok = as5600_get_angle(MOTION_I2C_INST, &current_motion_angle);

    if (motion_read_ok && motion_magnet_valid) {
        motion_err_count = 0;
        state.motion_angle = current_motion_angle;

        if (!motion_initialized) {
            prev_motion_angle = current_motion_angle;
            motion_initialized = true;
        } else {
            int32_t delta = (int32_t)current_motion_angle - (int32_t)prev_motion_angle;
            if (delta > 2048) {
                delta -= 4096;
            } else if (delta < -2048) {
                delta += 4096;
            }
            delta *= MOTION_DIRECTION_SIGN;

            if (abs(delta) < 400) {
                if (delta != 0) {
                    state.total_motion_counts += delta;
                    state.motion_full_turns = state.total_motion_counts / 4096;
                    state.total_motion_um = (int32_t)((double)state.total_motion_counts * BMG_UM_PER_COUNT);

                    float instant_velocity = (float)delta * BMG_UM_PER_COUNT * (1000000.0f / (float)UPDATE_INTERVAL_US);
                    filtered_velocity_um_s = (filtered_velocity_um_s * 0.90f) + (instant_velocity * 0.10f);
                } else {
                    filtered_velocity_um_s *= 0.95f;
                    if (fabsf(filtered_velocity_um_s) < 50.0f) {
                        filtered_velocity_um_s = 0.0f;
                    }
                }
                prev_motion_angle = current_motion_angle;
            }
        }
    } else {
        motion_err_count++;
        if (motion_err_count % 25 == 2) {
            as5600_bus_recover(MOTION_I2C_INST, MOTION_SDA_PIN, MOTION_SCL_PIN, 100000);
        }
        if (motion_err_count >= 25) {
            filtered_velocity_um_s = 0.0f;
        }
        if (motion_err_count >= 250) {
            state.motion_magnet_state = MAGNET_STATE_NOT_DETECTED;
            motion_initialized = false;
        }
    }

    state.motion_velocity_um_s = (int16_t)filtered_velocity_um_s;
    if (state.motion_velocity_um_s < -500) {
        state.fault_flags |= FAULT_MOTION_REVERSE;
    }

    // 3. Diameter Module (10 mm Bearings - 250 Hz sampling)
    static uint32_t dia_err_count = 0;
    static uint32_t dia_runout_counter = 0;
    uint16_t current_dia_angle = 0;
    bool dia_read_ok = as5600_get_angle(DIAMETER_I2C_INST, &current_dia_angle);

    if (dia_read_ok && dia_magnet_valid) {
        dia_err_count = 0;
        state.diameter_raw_angle = current_dia_angle;

        if (!diameter_initialized) {
            filtered_dia_angle = (float)current_dia_angle;
            diameter_initialized = true;
        } else {
            float angle_delta = fabsf((float)current_dia_angle - filtered_dia_angle);
            if (angle_delta < 80.0f) {
                filtered_dia_angle = (filtered_dia_angle * 0.96f) + ((float)current_dia_angle * 0.04f);
                float ripple = fabsf((float)current_dia_angle - filtered_dia_angle);
                filtered_dia_ripple = (filtered_dia_ripple * 0.98f) + (ripple * 0.02f);
            }
        }

        float delta_from_zero = (filtered_dia_angle - dia_zero_angle) * dia_deflection_sign;
        if (delta_from_zero < 0.0f) delta_from_zero = 0.0f;
        int32_t calc_dia_um = (int32_t)(delta_from_zero * dia_um_per_count);
        
        if (calc_dia_um > 3500) calc_dia_um = 3500;
        state.diameter_filtered_um = (int16_t)calc_dia_um;
        state.diameter_variance_um = (int16_t)(filtered_dia_ripple * dia_um_per_count);

        if (state.diameter_filtered_um >= 800) {
            dia_runout_counter = 0;
            state.filament_present = 1;
            if (state.diameter_filtered_um < 1400 || state.diameter_filtered_um > 2100) {
                state.fault_flags |= FAULT_DIAMETER_OUT_OF_RANGE;
            }
        } else {
            if (++dia_runout_counter >= 50) {
                state.filament_present = 0;
                state.fault_flags |= FAULT_RUNOUT;
            }
        }
    } else {
        dia_err_count++;
        if (dia_err_count % 25 == 2) {
            as5600_bus_recover(DIAMETER_I2C_INST, DIAMETER_SDA_PIN, DIAMETER_SCL_PIN, 100000);
        }
        if (dia_err_count >= 250) {
            state.diameter_magnet_state = MAGNET_STATE_NOT_DETECTED;
            state.diameter_filtered_um = 0;
            state.diameter_variance_um = 0;
            state.filament_present = 0;
            state.fault_flags |= FAULT_RUNOUT;
            diameter_initialized = false;
        }
    }

    // 4. Motion Wheel Stall / Slip Detection
    if (state.filament_present && state.diameter_variance_um >= 5 && abs(state.motion_velocity_um_s) < 200) {
        stall_timer_ms += (UPDATE_INTERVAL_US / 1000);
        if (stall_timer_ms >= 1000) {
            state.fault_flags |= FAULT_MOTION_STALL;
        }
    } else {
        if (stall_timer_ms >= (UPDATE_INTERVAL_US / 1000)) stall_timer_ms -= (UPDATE_INTERVAL_US / 1000);
        else stall_timer_ms = 0;
    }

    // 5. Bed ADXL345 Telemetry & Crash/Jerk Detection (250 Hz sampling)
    int16_t ax_mg = 0, ay_mg = 0, az_mg = 0;
    bool adxl_ok = adxl345_read_accel_mg(BED_SPI_INST, BED_SPI_CS_PIN, &ax_mg, &ay_mg, &az_mg);

    if (adxl_ok) {
        state.bed_accel_x_mg = ax_mg;
        state.bed_accel_y_mg = ay_mg;
        state.bed_accel_z_mg = az_mg;

        if (!adxl_initialized) {
            prev_accel_x = ax_mg;
            prev_accel_y = ay_mg;
            prev_accel_z = az_mg;
            adxl_initialized = true;
            state.bed_peak_jerk = 0;
        } else {
            // Delta acceleration over 4 ms (Instantaneous jerk metric in mg/4ms)
            int32_t dx = (int32_t)ax_mg - (int32_t)prev_accel_x;
            int32_t dy = (int32_t)ay_mg - (int32_t)prev_accel_y;
            int32_t dz = (int32_t)az_mg - (int32_t)prev_accel_z;

            // Approximate Euclidean norm: sqrt(dx^2 + dy^2 + dz^2)
            int32_t mag_sq = dx * dx + dy * dy + dz * dz;
            int16_t instant_jerk = (int16_t)sqrtf((float)mag_sq);

            state.bed_peak_jerk = instant_jerk;
            prev_accel_x = ax_mg;
            prev_accel_y = ay_mg;
            prev_accel_z = az_mg;

            // Sudden shock / collision check
            if (instant_jerk >= BED_CRASH_JERK_THRESHOLD_MG) {
                crash_decay_counter = 25; // Hold crash fault for at least 100 ms (25 frames)
            }
        }
    } else {
        // Re-initialize ADXL if connection dropped momentarily
        static uint32_t adxl_retry = 0;
        if (++adxl_retry % 250 == 0) { // Retry once per second
            adxl345_init(BED_SPI_INST, BED_SPI_SCK_PIN, BED_SPI_MOSI_PIN, BED_SPI_MISO_PIN, BED_SPI_CS_PIN, BED_SPI_BAUDRATE_HZ);
        }
    }

    if (crash_decay_counter > 0) {
        crash_decay_counter--;
        state.fault_flags |= FAULT_BED_CRASH;
    }
}

// -----------------------------------------------------------------------------
// Host Binary Serial Packet (38 bytes payload + 3 bytes header)
// -----------------------------------------------------------------------------
static void send_binary_packet(void) {
    uint8_t packet[3 + sizeof(struct sensor_state_t)];
    packet[0] = RESP_HEADER_1;
    packet[1] = RESP_HEADER_2;
    packet[2] = CMD_READ_ALL;
    memcpy(&packet[3], &state, sizeof(struct sensor_state_t));

    for (size_t i = 0; i < sizeof(packet); i++) {
        putchar_raw(packet[i]);
    }
    stdio_flush();
}

// -----------------------------------------------------------------------------
// USB Command Processor
// -----------------------------------------------------------------------------
static void handle_usb_input(void) {
    int ch = getchar_timeout_us(0);
    if (ch == PICO_ERROR_TIMEOUT) {
        return;
    }

    if (ch == CMD_PREFIX) {
        int reg = getchar_timeout_us(5000);
        if (reg == CMD_READ_ALL) {
            send_binary_packet();
        } else if (reg == CMD_RESET_MOTION) {
            state.total_motion_counts = 0;
            state.total_motion_um = 0;
            state.motion_full_turns = 0;
        } else if (reg == CMD_TARE_DIAMETER || reg == CMD_TARE_EMPTY) {
            dia_zero_angle = filtered_dia_angle;
            config_save_to_flash();
        } else if (reg == CMD_CAL_SPAN) {
            int low = getchar_timeout_us(10000);
            int high = getchar_timeout_us(10000);
            if (low != PICO_ERROR_TIMEOUT && high != PICO_ERROR_TIMEOUT) {
                uint16_t cal_um = (uint16_t)low | ((uint16_t)high << 8);
                float raw_diff = filtered_dia_angle - dia_zero_angle;
                float count_diff = fabsf(raw_diff);
                if (count_diff > 10.0f && cal_um > 500) {
                    dia_deflection_sign = (raw_diff >= 0.0f) ? 1.0f : -1.0f;
                    dia_um_per_count = (float)cal_um / count_diff;
                    config_save_to_flash();
                }
            }
        } else if (reg == CMD_SAVE_CONFIG) {
            config_save_to_flash();
        }
    } else if (ch == 'd' || ch == 'D' || ch == 't' || ch == 'T') {
        debug_stream_enabled = !debug_stream_enabled;
        if (debug_stream_enabled) {
            printf("\n--- Starting Live Telemetry Stream with Bed ADXL (press 'd' to pause) ---\n");
        } else {
            printf("\n--- Telemetry Stream Paused ---\n");
        }
    } else if (ch == 'z' || ch == 'Z') {
        state.total_motion_counts = 0;
        state.total_motion_um = 0;
        state.motion_full_turns = 0;
        printf("\n[RESET] Motion distance and turns reset to 0.00 mm\n");
    } else if (ch == 'e' || ch == 'E') {
        dia_zero_angle = filtered_dia_angle;
        config_save_to_flash();
        printf("\n[CALIBRATE] Empty bearing reference tared to 0.000 mm (angle: %.1f) & saved to Flash!\n", dia_zero_angle);
    } else if (ch == 'c' || ch == 'C') {
        char buf[16] = {0};
        int idx = 0;
        int next_ch;
        while ((next_ch = getchar_timeout_us(25000)) != PICO_ERROR_TIMEOUT) {
            if (next_ch == '\r' || next_ch == '\n') break;
            if (idx < 15 && ((next_ch >= '0' && next_ch <= '9') || next_ch == '.' || next_ch == ' ')) {
                buf[idx++] = (char)next_ch;
            }
        }
        buf[idx] = '\0';
        float target_mm = 1.75f;
        if (idx > 0) {
            float parsed = (float)atof(buf);
            if (parsed >= 0.5f && parsed <= 3.5f) {
                target_mm = parsed;
            }
        }
        float raw_diff = filtered_dia_angle - dia_zero_angle;
        float count_diff = fabsf(raw_diff);
        if (count_diff > 10.0f) {
            dia_deflection_sign = (raw_diff >= 0.0f) ? 1.0f : -1.0f;
            dia_um_per_count = (target_mm * 1000.0f) / count_diff;
            config_save_to_flash();
            printf("\n[CALIBRATE] Filament span calibrated to %.3f mm! Scale: %.2f um/count (saved to Flash)\n",
                   target_mm, dia_um_per_count);
        } else {
            printf("\n[CALIBRATE] Deflection too small (%.1f counts). Ensure filament is seated!\n", count_diff);
        }
    } else if (ch == 'w' || ch == 'W') {
        config_save_to_flash();
        printf("\n[FLASH] Calibration parameters successfully written to non-volatile Flash!\n");
    } else if (ch == 'b' || ch == 'B') {
        printf("\n[BOOTLOADER] Jumping to bootloader...\n");
        sleep_ms(100);
        jump_to_bootloader();
    }
}

// -----------------------------------------------------------------------------
// Main Entry Point
// -----------------------------------------------------------------------------
int main(void) {
    stdio_init_all();

    // Load persistent calibration from Flash if available
    config_load_from_flash();

    // Configure filament runout switch pin
    gpio_init(FILAMENT_RUNOUT_PIN);
    gpio_set_dir(FILAMENT_RUNOUT_PIN, GPIO_IN);
    gpio_pull_up(FILAMENT_RUNOUT_PIN);

    // Initialize I2C buses (100 kHz Standard-Mode)
    as5600_init_bus(MOTION_I2C_INST, MOTION_SDA_PIN, MOTION_SCL_PIN, 100000);
    as5600_init_bus(DIAMETER_I2C_INST, DIAMETER_SDA_PIN, DIAMETER_SCL_PIN, 100000);

    sleep_ms(50);
    as5600_configure_fast(MOTION_I2C_INST);
    as5600_configure_smooth(DIAMETER_I2C_INST);

    // Initialize Bed ADXL345 SPI (1.0 MHz Clock for 32-inch cable integrity)
    bool adxl_init_ok = adxl345_init(BED_SPI_INST, BED_SPI_SCK_PIN, BED_SPI_MOSI_PIN, BED_SPI_MISO_PIN, BED_SPI_CS_PIN, BED_SPI_BAUDRATE_HZ);

    memset(&state, 0, sizeof(state));
    state.motion_magnet_state = MAGNET_STATE_UNKNOWN;
    state.diameter_magnet_state = MAGNET_STATE_UNKNOWN;

    sleep_ms(300);

    // Enable hardware watchdog (2000 ms timeout, pause during debugging)
    watchdog_enable(2000, 1);

    last_update_time = time_us_64();
    uint64_t last_debug_print = 0;

    while (1) {
        watchdog_update();
        uint64_t now = time_us_64();

        // 250 Hz sensor polling loop
        if (now - last_update_time >= UPDATE_INTERVAL_US) {
            last_update_time = now;
            update_sensors();

            // Periodic ASCII stream if enabled (5 Hz)
            if (debug_stream_enabled && (now - last_debug_print >= 200000)) {
                last_debug_print = now;
                float pos_mm = (float)state.total_motion_um / 1000.0f;
                float dia_mm = (float)state.diameter_filtered_um / 1000.0f;

                printf("[MOT] %+.2fmm (%4ld) | [DIA] %.3fmm | [BED] X:%+5d Y:%+5d Z:%+5d mg | Jerk:%4d %s\n",
                       pos_mm, (long)state.motion_angle,
                       dia_mm,
                       state.bed_accel_x_mg, state.bed_accel_y_mg, state.bed_accel_z_mg,
                       state.bed_peak_jerk,
                       (state.fault_flags & FAULT_BED_CRASH) ? "[CRASH!]" : "");
            }
        }

        handle_usb_input();
    }

    return 0;
}
