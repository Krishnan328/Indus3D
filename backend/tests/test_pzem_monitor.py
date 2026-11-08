import pytest
import struct
from services.pzem_monitor import (
    crc16_modbus,
    _build_request,
    _parse_response,
    _DISCONNECTED,
)


def test_crc16_modbus_known_vector():
    # PZEM Read Input Registers request: 01 04 00 00 00 0A
    data = bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x0A])
    crc = crc16_modbus(data)
    # Check little-endian bytes: 0x70, 0x0D -> crc = 0x0D70
    crc_bytes = struct.pack("<H", crc)
    assert crc_bytes == bytes([0x70, 0x0D])


def test_build_request():
    req = _build_request(addr=1)
    assert len(req) == 8
    assert req[:6] == bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x0A])
    assert req[6:] == bytes([0x70, 0x0D])


def test_parse_response_valid():
    # Real payload from live PZEM hardware:
    # 01 04 14 08 f8 00 00 00 00 00 00 00 00 00 01 00 00 01 f4 00 00 00 00 58 28
    # 08f8 = 2300 -> 230.0V
    # current = 0
    # power = 0
    # energy = 1 Wh
    # freq = 01f4 = 500 -> 50.0 Hz
    # pf = 0
    raw = bytes.fromhex("01041408f800000000000000000001000001f4000000005828")
    parsed = _parse_response(raw, addr=1)
    assert parsed is not None
    assert parsed["connected"] is True
    assert parsed["voltage"] == 229.6  # 0x08f8 = 2296 -> 229.6 V
    assert parsed["current"] == 0.0
    assert parsed["power"] == 0.0
    assert parsed["energy"] == 1
    assert parsed["energy_wh"] == 1
    assert parsed["frequency"] == 50.0
    assert parsed["power_factor"] == 0.0


def test_parse_response_corrupted_crc():
    raw = bytearray.fromhex("01041408f800000000000000000001000001f4000000005828")
    raw[-1] ^= 0xFF  # Corrupt CRC
    parsed = _parse_response(bytes(raw), addr=1)
    assert parsed is None


def test_parse_response_short_frame():
    assert _parse_response(b"\x01\x04\x05", addr=1) is None
