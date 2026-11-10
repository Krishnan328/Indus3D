cmake_minimum_required(VERSION 3.13)

# Include Pico SDK
include(pico_sdk_import.cmake)

project(smart_filament_sensor C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Raspberry Pi Pico SDK
pico_sdk_init()

add_executable(smart_filament_sensor
    main.c
    as5600.c
)

# Optional flash offset for Katapult bootloader (RP2040 only)
option(ENABLE_KATAPULT_OFFSET "Offset flash for Katapult bootloader" OFF)
if(ENABLE_KATAPULT_OFFSET)
    pico_add_linker_script_override_path(smart_filament_sensor ${CMAKE_CURRENT_LIST_DIR}/katapult_link FILES pico_flash_region.ld section_boot2.incl)
endif()

# Pull in common SDK features
target_link_libraries(smart_filament_sensor
    pico_stdlib
    hardware_i2c
    hardware_gpio
    hardware_timer
    hardware_flash
    hardware_sync
    hardware_watchdog
    pico_bootsel_via_double_reset
)

# Enable USB CDC serial output and disable UART stdio (so USB connects directly to Host/Klipper)
pico_enable_stdio_usb(smart_filament_sensor 1)
pico_enable_stdio_uart(smart_filament_sensor 0)

# Set USB stdout timeout to 5 ms (5000 us) so buffers flush without freezing the loop
target_compile_definitions(smart_filament_sensor PRIVATE
    PICO_STDIO_USB_STDOUT_TIMEOUT_US=5000
)

# Generate UF2, bin, hex, and elf outputs
pico_add_extra_outputs(smart_filament_sensor)

# ==============================================================================
# Development Target with Bed ADXL345 Telemetry & Crash Detection
# ==============================================================================
add_executable(smart_filament_sensor_adxl
    main_with_adxl.c
    as5600.c
    adxl345.c
)

if(ENABLE_KATAPULT_OFFSET)
    pico_add_linker_script_override_path(smart_filament_sensor_adxl ${CMAKE_CURRENT_LIST_DIR}/katapult_link FILES pico_flash_region.ld section_boot2.incl)
endif()

target_link_libraries(smart_filament_sensor_adxl
    pico_stdlib
    hardware_i2c
    hardware_spi
    hardware_gpio
    hardware_timer
    hardware_flash
    hardware_sync
    hardware_watchdog
    pico_bootsel_via_double_reset
)

pico_enable_stdio_usb(smart_filament_sensor_adxl 1)
pico_enable_stdio_uart(smart_filament_sensor_adxl 0)

target_compile_definitions(smart_filament_sensor_adxl PRIVATE
    PICO_STDIO_USB_STDOUT_TIMEOUT_US=5000
)

pico_add_extra_outputs(smart_filament_sensor_adxl)

