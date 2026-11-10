/**
 * Smart Filament Sensor Firmware for Raspberry Pi Pico / RP2040
 * Combines high-resolution motion tracking (Roadrunner/BMG) & diameter sensing (Infidel).
 * 
 * Sensor 1 (Motion):   I2C0 on GP4 (SDA) / GP5 (SCL)
 * Sensor 2 (Diameter): I2C1 on GP2 (SDA) / GP3 (SCL)
 * Optional Runout Pin: GP6 (Active Low, internal pull-up)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "pico/stdlib.h"
#include "hardware/timer.h"
#include "hardware/sync.h"
#include "hardware/flash.h"
#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include "as5600.h"

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

#define UPDATE_INTERVAL_US      4000 // 4 ms (250 Hz main loop - 10x faster than host, rock-solid I2C headroom)

// -----------------------------------------------------------------------------
// Mechanical & Geometric Calibration Parameters
// -----------------------------------------------------------------------------
// 1. Motion Module: Bondtech BMG Extruder Gear Set
static float bmg_circumference_um       = 25273.0f;                                      // 25.273 mm per 360 deg
#define BMG_UM_PER_COUNT                (bmg_circumference_um / 4096.0f)                 // ~6.1702 um/count (162.07 counts/mm)
#define MOTION_DIRECTION_SIGN           (-1)                                             // Inverted: forward filament feed increases distance

// 2. Diameter Module: Modified Infidel (10 mm Bearings)
// Calibrated geometry: 1.75 mm filament = 14.5314 deg deflection anticlockwise
#define NOMINAL_FILAMENT_DIAMETER_UM    1750
#define DEFLECTION_DEG_PER_1750UM       14.5314f
// Default Diameter Deflection: -1.0f because inserting filament decreases AS5600 angle (bearings push apart)
#define DEFAULT_DIAMETER_DEFLECTION_SIGN (-1.0f)
#define DEFAULT_DIA_ZERO_ANGLE          (3080.0f) // Resting angle of empty bearings (hardware calibrated)
#define DEFAULT_DIA_UM_PER_COUNT        (9.4118f) // 1.76 mm / 187 counts deflection (hardware calibrated)

// Fault Bitmasks
#define FAULT_OK                        0x00
#define FAULT_MOTION_STALL              0x01 // Diameter ripple active but motion wheel stationary
#define FAULT_MOTION_REVERSE            0x02 // Filament retracting / moving backwards
#define FAULT_DIAMETER_OUT_OF_RANGE     0x04 // Diameter < 1.40 mm or > 2.10 mm
#define FAULT_RUNOUT                    0x08 // Filament absent or magnet lost

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

// Sensor state struct (packed for binary serial transmission - 30 bytes payload)
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
// Sensor Update Logic (Executed at 100 Hz)
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

        // Only update validity if magnitude was successfully read over I2C
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
            // Zero-crossing handling
            if (delta > 2048) {
                delta -= 4096;
            } else if (delta < -2048) {
                delta += 4096;
            }
            delta *= MOTION_DIRECTION_SIGN;

            // Glitch rejection: in 4 ms, BMG gear cannot rotate > 400 counts (~2.5 mm, or 625 mm/s)
            if (abs(delta) < 400) {
                if (delta != 0) {
                    state.total_motion_counts += delta;
                    state.motion_full_turns = state.total_motion_counts / 4096;
                    state.total_motion_um = (int32_t)((double)state.total_motion_counts * BMG_UM_PER_COUNT);

                    // Instantaneous velocity (delta counts * um_per_count / dt)
                    float instant_velocity = (float)delta * BMG_UM_PER_COUNT * (1000000.0f / (float)UPDATE_INTERVAL_US); // um/s
                    filtered_velocity_um_s = (filtered_velocity_um_s * 0.90f) + (instant_velocity * 0.10f);
                } else {
                    filtered_velocity_um_s *= 0.95f; // Decay when still
                    if (fabsf(filtered_velocity_um_s) < 50.0f) {
                        filtered_velocity_um_s = 0.0f;
                    }
                }
                prev_motion_angle = current_motion_angle;
            }
        }
    } else {
        motion_err_count++;
        // Periodic bus recovery on errors (every 25 dropped frames = 100 ms)
        if (motion_err_count % 25 == 2) {
            as5600_bus_recover(MOTION_I2C_INST, MOTION_SDA_PIN, MOTION_SCL_PIN, 100000);
        }
        // Sample-and-Hold: only zero velocity after 25 consecutive dropped reads (100 ms)
        // Keep reference angle and accumulated counts safe!
        if (motion_err_count >= 25) {
            filtered_velocity_um_s = 0.0f;
        }
        // Only declare uninitialized after >250 consecutive dropped reads (1.0 full second)
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
            // Glitch rejection filter: in 4 ms, caliper cannot mechanically move > 80 counts (>0.8 mm)
            float angle_delta = fabsf((float)current_dia_angle - filtered_dia_angle);
            if (angle_delta < 80.0f) {
                // Smooth Exponential Moving Average filter
                filtered_dia_angle = (filtered_dia_angle * 0.96f) + ((float)current_dia_angle * 0.04f);

                // High-pass ripple estimation (micro-texture of moving filament)
                float ripple = fabsf((float)current_dia_angle - filtered_dia_angle);
                filtered_dia_ripple = (filtered_dia_ripple * 0.98f) + (ripple * 0.02f);
            }
        }

        // Calibrated diameter relative to empty bearing zero:
        float delta_from_zero = (filtered_dia_angle - dia_zero_angle) * dia_deflection_sign;
        if (delta_from_zero < 0.0f) delta_from_zero = 0.0f;
        int32_t calc_dia_um = (int32_t)(delta_from_zero * dia_um_per_count);
        
        // Constrain to reasonable measurement limits (0.00 mm - 3.50 mm)
        if (calc_dia_um > 3500) calc_dia_um = 3500;
        state.diameter_filtered_um = (int16_t)calc_dia_um;

        // Ripple variance in micrometers
        state.diameter_variance_um = (int16_t)(filtered_dia_ripple * dia_um_per_count);

        // Dynamic electronic runout detection with BDWidth-style tolerance count (debounce):
        // Filament is present if diameter >= 0.80 mm
        if (state.diameter_filtered_um >= 800) {
            dia_runout_counter = 0;
            state.filament_present = 1;
            // Check tolerance limits (1.40 mm to 2.10 mm)
            if (state.diameter_filtered_um < 1400 || state.diameter_filtered_um > 2100) {
                state.fault_flags |= FAULT_DIAMETER_OUT_OF_RANGE;
            }
        } else {
            // Require 50 consecutive low samples (200 ms) before declaring runout to prevent transient dips
            if (++dia_runout_counter >= 50) {
                state.filament_present = 0;
                state.fault_flags |= FAULT_RUNOUT;
            }
        }
    } else {
        dia_err_count++;
        // Periodic bus recovery on errors (every 25 dropped frames = 100 ms)
        if (dia_err_count % 25 == 2) {
            as5600_bus_recover(DIAMETER_I2C_INST, DIAMETER_SDA_PIN, DIAMETER_SCL_PIN, 100000);
        }
        // SAMPLE-AND-HOLD: DO NOT zero out diameter on temporary I2C drops!
        // Retain the last known valid diameter reading so Klipper/daemon flow remains rock steady.
        // Only if I2C has been completely dead for 250 consecutive samples (1.0 full second):
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
        if (stall_timer_ms >= 1000) { // 1 second (1000 ms) of persistent slip/stall
            state.fault_flags |= FAULT_MOTION_STALL;
        }
    } else {
        if (stall_timer_ms >= (UPDATE_INTERVAL_US / 1000)) stall_timer_ms -= (UPDATE_INTERVAL_US / 1000);
        else stall_timer_ms = 0;
    }
}

// -----------------------------------------------------------------------------
// Host Binary Serial Packet
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
            printf("\n--- Starting Live Telemetry Stream (press 'd' to pause) ---\n");
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
        // Read optional custom diameter parameter (e.g. 'c 1.72\n' or just 'c\n')
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
            printf("\n[CALIBRATE] Filament span calibrated to %.3f mm! Count diff: %.1f (dir: %+.0f), Scale: %.2f um/count (saved to Flash)\n",
                   target_mm, count_diff, dia_deflection_sign, dia_um_per_count);
        } else {
            printf("\n[CALIBRATE] Deflection too small (%.1f counts). Ensure filament is seated!\n", count_diff);
        }
    } else if (ch == 'w' || ch == 'W') {
        config_save_to_flash();
        printf("\n[FLASH] Calibration parameters successfully written to non-volatile Flash!\n");
    } else if (ch == 's' || ch == 'S') {
    } else if (ch == 's' || ch == 'S') {
        printf("\n--- Scanning ALL RP2040 I2C Pin Pairs for AS5600 (0x36) ---\n");
        const struct {
            uint sda;
            uint scl;
            i2c_inst_t *inst;
            const char *name;
        } pairs[] = {
            {2, 3, i2c1, "GP2 / GP3 (Pin 4/5) [Default Diameter]"},
            {4, 5, i2c0, "GP4 / GP5 (Pin 6/7) [Default Motion]"},
            {0, 1, i2c0, "GP0 / GP1 (Pin 1/2)"},
            {6, 7, i2c1, "GP6 / GP7 (Pin 9/10)"},
            {8, 9, i2c0, "GP8 / GP9 (Pin 11/12)"},
            {10, 11, i2c1, "GP10 / GP11 (Pin 14/15)"},
            {12, 13, i2c0, "GP12 / GP13 (Pin 16/17)"},
            {14, 15, i2c1, "GP14 / GP15 (Pin 19/20)"},
            {16, 17, i2c0, "GP16 / GP17 (Pin 21/22)"},
            {18, 19, i2c1, "GP18 / GP19 (Pin 24/25)"},
            {20, 21, i2c0, "GP20 / GP21 (Pin 26/27)"},
            {26, 27, i2c1, "GP26 / GP27 (Pin 31/32)"},
        };

        int found_count = 0;
        for (size_t i = 0; i < sizeof(pairs)/sizeof(pairs[0]); i++) {
            // First check raw GPIO levels with pull-ups
            gpio_set_function(pairs[i].sda, GPIO_FUNC_SIO);
            gpio_set_function(pairs[i].scl, GPIO_FUNC_SIO);
            gpio_set_dir(pairs[i].sda, GPIO_IN);
            gpio_set_dir(pairs[i].scl, GPIO_IN);
            gpio_pull_up(pairs[i].sda);
            gpio_pull_up(pairs[i].scl);
            sleep_us(50);
            int sda_lvl = gpio_get(pairs[i].sda);
            int scl_lvl = gpio_get(pairs[i].scl);

            // Re-init as I2C
            as5600_init_bus(pairs[i].inst, pairs[i].sda, pairs[i].scl, 100000);
            uint16_t ang = 0;
            bool ok = as5600_get_angle(pairs[i].inst, &ang);
            uint8_t stat = 0;
            as5600_read8(pairs[i].inst, AS5600_REG_STATUS, &stat);

            if (ok) {
                found_count++;
                printf("  [FOUND] %-38s -> Angle: %4u, Stat: 0x%02X\n",
                       pairs[i].name, ang, stat);
            } else if (sda_lvl == 0 || scl_lvl == 0) {
                printf("  [WARN]  %-38s -> Pin stuck LOW (SDA=%d, SCL=%d)\n",
                       pairs[i].name, sda_lvl, scl_lvl);
            } else if (i < 2) {
                // Always report default pins even if empty
                printf("  [INFO]  %-38s -> No response (SDA=%d, SCL=%d)\n",
                       pairs[i].name, sda_lvl, scl_lvl);
            }
        }

        if (found_count == 0) {
            printf("  --> No AS5600 devices responded on any tested pin pair.\n");
        }

        // Restore active buses
        as5600_init_bus(MOTION_I2C_INST, MOTION_SDA_PIN, MOTION_SCL_PIN, 100000);
        as5600_init_bus(DIAMETER_I2C_INST, DIAMETER_SDA_PIN, DIAMETER_SCL_PIN, 100000);
        printf("--- Scan Complete ---\n");
        stdio_flush();
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

    // Initialize I2C buses (100 kHz Standard-Mode for rock-solid signal integrity)
    as5600_init_bus(MOTION_I2C_INST, MOTION_SDA_PIN, MOTION_SCL_PIN, 100000);
    as5600_init_bus(DIAMETER_I2C_INST, DIAMETER_SDA_PIN, DIAMETER_SCL_PIN, 100000);

    sleep_ms(50);
    // Configure AS5600 hardware filters:
    // Motion: fast tracking (6 LSB threshold, 2x slow filter, 2 LSB hysteresis)
    as5600_configure_fast(MOTION_I2C_INST);
    // Diameter: ultra-smooth precision (16x slow filter, slow filter only, 3 LSB hysteresis)
    as5600_configure_smooth(DIAMETER_I2C_INST);

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

        // 100 Hz sensor polling loop
        if (now - last_update_time >= UPDATE_INTERVAL_US) {
            last_update_time = now;
            update_sensors();

            // Periodic ASCII stream if enabled (5 Hz)
            if (debug_stream_enabled && (now - last_debug_print >= 200000)) {
                last_debug_print = now;
                uint8_t m_stat = 0, m_agc = 0, d_stat = 0, d_agc = 0;
                uint16_t m_mag = 0, d_mag = 0;
                as5600_read8(MOTION_I2C_INST, AS5600_REG_STATUS, &m_stat);
                as5600_get_agc(MOTION_I2C_INST, &m_agc);
                as5600_get_magnitude(MOTION_I2C_INST, &m_mag);
                as5600_read8(DIAMETER_I2C_INST, AS5600_REG_STATUS, &d_stat);
                as5600_get_agc(DIAMETER_I2C_INST, &d_agc);
                as5600_get_magnitude(DIAMETER_I2C_INST, &d_mag);

                float pos_mm = (float)state.total_motion_um / 1000.0f;
                printf("[MOT] ang:%4ld stat:0x%02X agc:%3d mag:%4d | [DIA] ang:%4ld stat:0x%02X agc:%3d mag:%4d | pos:%+.2fmm\n",
                       (long)state.motion_angle, m_stat, m_agc, m_mag,
                       (long)state.diameter_raw_angle, d_stat, d_agc, d_mag,
                       pos_mm);
            }
        }

        handle_usb_input();
    }

    return 0;
}
