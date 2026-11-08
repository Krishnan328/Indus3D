# Hardware Pinout & Wiring Specification
## Indus3D ESP8266 Multi-Sensor Hub (Bed Collision Monitor + Input Shaping + Chamber Telemetry)

This document provides complete electrical wiring, pinout tables, signal routing recommendations, and critical boot-strap hardware constraints for connecting an **ESP8266** (NodeMCU v2/v3 or Wemos D1 Mini) to an **ADXL345** (mounted on the printer's Y-carriage / bed frame) and a **BME280** (enclosure / chamber environmental sensor).

---

## 1. Complete Pinout Table

| Sensor Signal | Sensor Pin | ESP8266 GPIO | NodeMCU / D1 Pin | Interface Type | Hardware / Boot Notes |
|---|---|---|---|---|---|
| **ADXL345 CS** | CS | **GPIO16** | **D0** | Hardware SPI (HSPI) | **Recommended!** (Connect to D0/GPIO16 to prevent boot mode 7,7 hang). |
| **ADXL345 SCK** | SCL / SCK | **GPIO14** | **D5** | Hardware SPI (HSPI) | Clock line (up to 5 MHz) |
| **ADXL345 MISO**| SDO / MISO| **GPIO12** | **D6** | Hardware SPI (HSPI) | Master In / Slave Out |
| **ADXL345 MOSI**| SDA / MOSI| **GPIO13** | **D7** | Hardware SPI (HSPI) | Master Out / Slave In |
| **ADXL345 VCC** | VCC | 3V3 / 5V | 3V3 or 5V | Power | Use 3V3 for raw chip; 5V if module has 662K LDO |
| **ADXL345 GND** | GND | GND | GND | Power | Star ground back to ESP8266 GND |
| **BME280 SCL**  | SCL | **GPIO2** | **D4** | Software I2C | Clock (100 kHz). Boot strap pin: must be HIGH at power-up (the module's pull-up does that) |
| **BME280 SDA**  | SDA | **GPIO0** | **D3** | Software I2C | Data. Boot strap pin (LOW = flash mode): the module's pull-up keeps it HIGH. Also the NodeMCU FLASH button |
| **BME280 VCC**  | VCC | 3V3 | 3V3 | Power | 3.3V regulated power rail |
| **BME280 GND**  | GND | GND | GND | Power | Ground return |
| **Status LED**  | Built-in | GPIO2 | D4 | Active LOW | **Not driven by the firmware**: GPIO2 is the BME280's clock line, the LED just follows it |

---

## 2. Schematic & Wiring Diagram

```text
                       +-------------------+
                       |  ESP8266 NodeMCU  |
                       |  / Wemos D1 Mini  |
                       +-------------------+
                       |                   |
    +--------------+   |                   |   +---------------------+
    |   ADXL345    |   |                   |   |       BME280        |
    | (Y-Carriage) |   |                   |   | (Chamber Enclosure) |
    +--------------+   |                   |   +---------------------+
    |  VCC (3.3V)  |<--| 3V3           3V3 |--->| VCC (3.3V)          |
    |  GND         |<--| GND           GND |--->| GND                 |
    |  CS (D0)     |<--| GPIO16 (D0)       |   |                     |
    |  SCK (D5)    |<--| GPIO14 (D5)       |   |                     |
    |  MISO (D6)   |-->| GPIO12 (D6)       |   |                     |
    |  MOSI (D7)   |<--| GPIO13 (D7)       |   |                     |
    +--------------+   |                   |   |                     |
                       |        GPIO2 (D4) |--->| SCL                 |
                       |        GPIO0 (D3) |<-->| SDA                 |
                       +-------------------+   +---------------------+
                                 |
                                 v
                         [USB Micro / Type-C]
                                 |
                        (To Host / Raspberry Pi)
```

---

## 3. Critical Hardware & Boot-Strap Considerations

### 3.1 Boot-strap pins used by this wiring
The chip select is on **GPIO16 (D0)** and the BME280 on **GPIO0 / GPIO2**, so nothing on the bus touches GPIO15 (which must stay LOW at boot; leave D8 unconnected and do not add a pull-up to it). This pin assignment is the one verified on the real hardware.

- **GPIO0 (SDA)** is the flash-mode strap: LOW at power-up means "download mode". The BME280 breakout's pull-up holds it HIGH. A breakout without pull-ups, or a very long SDA cable, can leave it floating: if the board will not start from power-up but works after pressing reset, add a 4.7 kΩ pull-up from GPIO0 to 3V3.
- **GPIO2 (SCL)** must be HIGH at power-up as well (same pull-up).
- Uploading firmware with `pio run --target upload` toggles these lines through the USB-serial chip as usual; disconnect nothing.
- **GPIO16 (CS)** has no strap function. It is, however, the deep-sleep wake pin and has no internal pull-up: the ADXL345 driver drives it HIGH (deselected) when it starts (`begin()`), a few hundred milliseconds after power-up.

### 3.2 Cable Length & High-Speed SPI Signal Integrity
- The ADXL345 operates at **5 MHz SPI** in this firmware to minimize CPU cycle consumption during 200 Hz crash monitoring and 1600 Hz input shaping.
- Mount the ESP8266 directly on or immediately adjacent to the printer's Y-carriage / bed frame (e.g. using a 3D printed mount).
- Use a short ribbon cable (**2 to 3 inches / 5 to 8 cm maximum**) between the ESP8266 and the ADXL345.
- Interleave GND wires between high-speed clock (`SCK`) and data lines (`MISO`, `MOSI`) if ribbon cable allows, or twist GND loosely around SCK to prevent inductive ringing and crosstalk from the Y-axis stepper motor coils.

### 3.3 Power Supply Decoupling
- Add a 100 nF ceramic decoupling capacitor directly between the `VCC` and `GND` pins of the ADXL345 breakout board.
- If using the **GY-291** breakout module, it typically incorporates an onboard **662K 3.3V LDO regulator**. If powering via 5V, ensure the solder jumper on the back of the GY-291 (if present) is properly configured for your supply voltage. Connecting 3.3V directly to the module's 3V3 input is recommended to bypass LDO dropout voltage.

### 3.4 BME280 I2C Bus & Address Selection
- The BME280 communicates over (software) I2C on GPIO0 (`D3`, SDA) and GPIO2 (`D4`, SCL).
- The firmware automatically scans both `0x76` (SDO pin to GND) and `0x77` (SDO pin to VCC).
- The BME280 cable can be longer (up to 30–50 cm) to allow flexible placement inside the printer enclosure, well away from direct hotbed radiant heat or cooling fan exhaust.
