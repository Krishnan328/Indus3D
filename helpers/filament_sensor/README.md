# Smart Filament Sensor (Pico RP2040 / Pico W)

Combines high-resolution filament motion tracking (inspired by Roadrunner) and real-time diameter sensing (inspired by Infidel) using a single Raspberry Pi Pico and two AS5600 magnetic rotary encoders.

---

## 1. Hardware Wiring

| Sensor | Function | AS5600 Pin | Pico GPIO | Pico Physical Pin |
| :--- | :--- | :--- | :--- | :--- |
| **Both** | Power | `VCC` | `3V3 OUT` | **Pin 36** |
| **Both** | Ground | `GND` | `GND` | **Pin 38 (or Pin 3)** |
| **Sensor 1 (Diameter)**| I2C1 SDA | `SDA` | **GP2** | **Pin 4** |
| **Sensor 1 (Diameter)**| I2C1 SCL | `SCL` | **GP3** | **Pin 5** |
| **Sensor 2 (Motion)**  | I2C0 SDA | `SDA` | **GP4** | **Pin 6** |
| **Sensor 2 (Motion)**  | I2C0 SCL | `SCL` | **GP5** | **Pin 7** |
| *(Optional Runout Switch)* | Switch | `SIG` | **GP6** | **Pin 9** |

> **Important AS5600 Notes:**
> - Ensure your AS5600 board is running at **3.3V** (R1 resistor populated with 0Ω connects VCC to 3.3V VDD).
> - Magnets MUST be **diametrically magnetized**.
> - Connect the `DIR` pin on both AS5600 boards to `GND`.

---

## 2. Building the Firmware

### Option A: Using the VS Code Raspberry Pi Pico Extension
1. Open this folder in VS Code.
2. If prompted by the Raspberry Pi Pico extension, click **Configure Project**.
3. Click **Compile / Build** in the bottom status bar.
4. Output file `smart_filament_sensor.uf2` will be created in the `build/` directory.

### Option B: Using CMake from Terminal
```bash
mkdir build
cd build
cmake ..
make -j4
```

---

## 3. Flashing to the Pico

1. Hold down the **BOOTSEL** button on your Raspberry Pi Pico.
2. Plug the USB cable into your computer (or release the button 1 second after plugging in).
3. The Pico will appear as a USB mass storage drive named `RPI-RP2`.
4. Drag and drop `build/smart_filament_sensor.uf2` onto the `RPI-RP2` drive.
5. The Pico will automatically reboot and start running the firmware.

---

## 4. Testing & Verification

### Quick Terminal Check
Open any serial monitor (VS Code Serial Monitor, minicom, screen, or PuTTY) at 115200 baud:
- Press `d` to toggle live ASCII debug streaming on/off.
- Press `z` to reset the motion turn counter.

### Using the Python Live Dashboard
Run the included test script on your host machine:
```bash
python3 test_sensor.py
```
This displays real-time telemetry:
```text
[MOTION] Turns:    0 | Ang: 1420 (   124.8°) | Mag: DETECTED (OK) || [DIA] Ang: 2180 | Mag: DETECTED (OK) || [SW]: PRESENT
```
Move the magnets with your fingers or a screwdriver to verify angle changes and zero-crossing detection.
