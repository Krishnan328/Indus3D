"""
services/pzem_monitor.py
--------------------------
Reads power metrics from a PZEM-004T energy monitor via Modbus RTU over
RS485 (USB-serial FTDI adapter). Reuses the exact protocol the hardware
test script proved against real hardware:

  Request frame: [addr] 04 00 00 00 0A [CRC_lo] [CRC_hi]
  (function code 0x04 = Read Input Registers, starting at 0x0000, count=10)

  Response: [addr] 04 14 [20 bytes of register data] [CRC_lo] [CRC_hi]
  (0x14 = 20 bytes = 10 registers × 2 bytes each)

Register layout (PZEM-004T v3.0 documented Modbus map):
  Reg 0: Voltage         × 0.1 V
  Reg 1: Current (low)   × 0.001 A  (combined with Reg 2)
  Reg 2: Current (high)
  Reg 3: Power (low)     × 0.1 W    (combined with Reg 4)
  Reg 4: Power (high)
  Reg 5: Energy (low)    × 1 Wh     (combined with Reg 6)
  Reg 6: Energy (high)
  Reg 7: Frequency       × 0.1 Hz
  Reg 8: Power Factor    × 0.01
  Reg 9: Alarm status

CRC16 uses the Modbus polynomial 0xA001 (reflected representation of
the standard CRC-16/MODBUS used in all Modbus RTU implementations).

Error handling follows moonraker_client.py's pattern: never raise, never
block, log and return a safe default. Values are None (not zero) when
the sensor isn't connected — the frontend uses this to show "not connected"
instead of misleading zeros presented as real readings.

This module is NOT thread-safe for concurrent read() calls (serial port
is inherently single-threaded), but that's fine — it's only called from
telemetry_worker._tick() which runs sequentially on one thread.
"""

import glob
import logging
import os
import struct
import threading
import time
from config.settings import settings

# ── Safe default when PZEM is unavailable ─────────────────────────────────────
_DISCONNECTED = {
    "voltage":      None,
    "current":      None,
    "power":        None,
    "power_w":      None,
    "energy":       None,
    "energy_wh":    None,
    "frequency":    None,
    "power_factor": None,
    "alarm":        None,
    "connected":    False,
    "port":         None,
}


# ── CRC16 (Modbus) ───────────────────────────────────────────────────────────
def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS: polynomial 0xA001 (reflected), init 0xFFFF.
    Matches the exact CRC logic from the proven hardware test script."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _build_request(addr: int) -> bytes:
    """Build the Modbus RTU request frame to read all 10 input registers."""
    # Function code 0x04 (Read Input Registers), start=0x0000, count=0x000A
    frame = struct.pack(">BBHH", addr, 0x04, 0x0000, 0x000A)
    crc = crc16_modbus(frame)
    # CRC is appended little-endian (Modbus convention)
    frame += struct.pack("<H", crc)
    return frame


def _parse_response(data: bytes, addr: int):
    """Parse a valid PZEM response into a readings dict.
    Returns None if the response is malformed or CRC fails."""
    # Expected: [addr] [0x04] [0x14] [20 data bytes] [CRC_lo] [CRC_hi] = 25 bytes
    if len(data) < 25:
        return None

    # Validate address and function code
    if data[0] != addr or data[1] != 0x04:
        return None

    byte_count = data[2]
    if byte_count != 0x14:  # 20 bytes = 10 registers
        return None

    # CRC check — CRC is over all bytes except the last two
    payload = data[:23]
    received_crc = struct.unpack("<H", data[23:25])[0]
    if crc16_modbus(payload) != received_crc:
        return None

    # Parse the 10 registers (big-endian unsigned 16-bit each)
    regs = struct.unpack(">10H", data[3:23])

    voltage      = regs[0] * 0.1                          # V
    current      = ((regs[2] << 16) | regs[1]) * 0.001    # A
    power        = ((regs[4] << 16) | regs[3]) * 0.1      # W
    energy       = (regs[6] << 16) | regs[5]              # Wh
    frequency    = regs[7] * 0.1                           # Hz
    power_factor = regs[8] * 0.01
    alarm        = regs[9]

    return {
        "voltage":      round(voltage, 1),
        "current":      round(current, 3),
        "power":        round(power, 1),
        "power_w":      round(power, 1),
        "energy":       energy,
        "energy_wh":    energy,
        "frequency":    round(frequency, 1),
        "power_factor": round(power_factor, 2),
        "alarm":        alarm,
        "connected":    True,
    }


def find_pzem_port() -> str:
    """Find the PZEM serial port, checking settings first, then auto-discovering
    any FTDI / FT232 USB-UART device symlinks."""
    configured = getattr(settings, "PZEM_SERIAL_PORT", "") or ""
    if configured and (os.path.exists(configured) or os.path.islink(configured)):
        return configured

    # Auto-discovery fallback for FTDI FT232 UART adapters
    patterns = [
        "/dev/serial/by-id/*FT232*",
        "/dev/serial/by-id/*FTDI*",
        "/dev/serial/by-id/usb-FTDI*",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]

    return configured


# ── Serial connection manager ────────────────────────────────────────────────
class PZEMMonitor:
    """Owns the serial connection to the PZEM-004T. Uses a dedicated background
    worker thread to poll Modbus RTU at 1 Hz, caching the latest metrics so that
    read() is non-blocking and safe to call from high-frequency (25 Hz) loops."""

    def __init__(self):
        self._serial = None
        self._port = find_pzem_port()
        self._baud = getattr(settings, "PZEM_SERIAL_BAUD", 9600)
        self._addr = getattr(settings, "PZEM_MODBUS_ADDR", 1)
        self._request = _build_request(self._addr)
        self._last_error_log = 0.0  # rate-limit error logging
        self._latest = dict(_DISCONNECTED)
        self._lock = threading.Lock()
        self._running = True

        # Start non-blocking background polling daemon thread
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="pzem_reader")
        self._thread.start()

    def read(self) -> dict:
        """Read latest cached registers from the PZEM-004T. Never raises.
        Always returns in sub-microsecond time without blocking."""
        with self._lock:
            return dict(self._latest)

    def read_direct(self) -> dict:
        """Synchronous read of all registers. Useful for diagnostic testing."""
        port = self._port or find_pzem_port()
        if not port or not os.path.exists(port):
            return _DISCONNECTED

        try:
            self._ensure_connection()
            if self._serial is None:
                return _DISCONNECTED

            self._serial.reset_input_buffer()
            self._serial.write(self._request)
            response = self._serial.read(25)
            if len(response) < 25:
                self._log_error(f"incomplete response ({len(response)} bytes)")
                return _DISCONNECTED

            result = _parse_response(response, self._addr)
            if result is None:
                self._log_error("CRC mismatch or malformed response")
                return _DISCONNECTED

            result["port"] = self._port
            return result
        except Exception as e:
            self._log_error(str(e))
            self._close()
            return _DISCONNECTED

    def _worker_loop(self):
        """Background thread worker loop running at 1 Hz."""
        while self._running:
            try:
                # Dynamic port discovery if port was missing or disconnected
                if not self._port or not os.path.exists(self._port):
                    discovered = find_pzem_port()
                    if discovered and os.path.exists(discovered):
                        self._port = discovered
                        self._close()

                if not self._port or not os.path.exists(self._port):
                    with self._lock:
                        self._latest = dict(_DISCONNECTED)
                    time.sleep(2.0)
                    continue

                self._ensure_connection()
                if self._serial is None:
                    with self._lock:
                        self._latest = dict(_DISCONNECTED)
                    time.sleep(2.0)
                    continue

                # Clear stale input buffer
                self._serial.reset_input_buffer()

                # Send request frame
                self._serial.write(self._request)

                # Read response — 25 bytes expected
                response = self._serial.read(25)
                if len(response) == 25:
                    parsed = _parse_response(response, self._addr)
                    if parsed:
                        parsed["port"] = self._port
                        with self._lock:
                            self._latest = parsed
                    else:
                        self._log_error("CRC mismatch or malformed response")
                        with self._lock:
                            self._latest = dict(_DISCONNECTED)
                else:
                    self._log_error(f"incomplete response ({len(response)} bytes)")
                    with self._lock:
                        self._latest = dict(_DISCONNECTED)
                    self._close()

            except Exception as e:
                self._log_error(str(e))
                self._close()
                with self._lock:
                    self._latest = dict(_DISCONNECTED)

            # PZEM updates hardware registers every 1.0 second
            time.sleep(1.0)

    def _ensure_connection(self):
        """Open the serial port if not already open. Never raises."""
        if self._serial is not None:
            return
        if not self._port or not os.path.exists(self._port):
            return
        try:
            import serial
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,
            )
        except ImportError:
            self._log_error("pyserial not installed (pip install pyserial)")
        except Exception as e:
            self._log_error(f"serial open failed on {self._port}: {e}")
            self._serial = None

    def _close(self):
        """Close the serial port safely."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def _log_error(self, msg: str):
        """Rate-limited error logging — at most once per 30 seconds to avoid
        flooding the console when the PZEM is simply unplugged."""
        now = time.time()
        if now - self._last_error_log > 30:
            logging.info(f"⚡ PZEM: {msg}")
            self._last_error_log = now

    def stop(self):
        """Stop background worker."""
        self._running = False
        self._close()


# Module-level singleton, matching how MoonrakerClient is used
pzem_monitor = PZEMMonitor()
