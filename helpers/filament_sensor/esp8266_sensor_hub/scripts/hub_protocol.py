"""Wire protocol of the ESP8266 bed sensor hub (stdlib only, shared by the daemon, the CLI and the analyzer).

Text side (115200 baud, one line each):
    {"bed_accel": {...}, "chamber": {...}, "crash_detected": false, ...}      1 Hz telemetry JSON
    // Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[-420, +1850, -910] mg) -> Auto-pausing print!
    // SHAPER_SESSION_STARTED: duration=7 s, rate=1600 Hz, baud=921600
    // SHAPER_SESSION_ENDED: collected 11200 samples
Binary side (only between STARTED and ENDED): 15-byte packets  <BBHIhhhB
    [0xAA, 0x55, uint16 seq, uint32 time_us, int16 x, int16 y, int16 z, uint8 xor-checksum-of-first-14]
"""

import re
import struct
from typing import Dict, List, Optional, Tuple

PACKET_FORMAT = "<BBHIhhhB"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)          # 15
MAGIC_0, MAGIC_1 = 0xAA, 0x55
SCALE_G_PER_LSB = 0.00390625                          # ADXL345 full resolution: 3.90625 mg/LSB
GRAVITY_MM_S2 = 9806.65

STARTED_MARK = b"// SHAPER_SESSION_STARTED"
ENDED_MARK = b"// SHAPER_SESSION_ENDED"

_CRASH_RE = re.compile(
    r"BED_CRASH_DETECTED\s+jerk=(\d+)\s*mg\s*\(accel=\[\s*([+-]?\d+)\s*,\s*([+-]?\d+)\s*,\s*([+-]?\d+)\s*\]\s*mg\)")
_STARTED_RE = re.compile(rb"duration=(\d+)\s*s,\s*rate=(\d+)\s*Hz(?:,\s*baud=(\d+))?")
_RATE_WARN_RE = re.compile(r"WARN: rate limited to (\d+) Hz")


def checksum(first14: bytes) -> int:
    cs = 0
    for b in first14:
        cs ^= b
    return cs


def pack_frame(seq: int, time_us: int, x: int, y: int, z: int) -> bytes:
    pre = struct.pack("<BBHIhhh", MAGIC_0, MAGIC_1, seq & 0xFFFF, time_us & 0xFFFFFFFF, x, y, z)
    return pre + bytes([checksum(pre)])


def parse_crash_line(line: str) -> Optional[Dict]:
    """The ESP's immediate alert line -> {"jerk_mg", "accel": {"x","y","z"}} (or None)."""
    m = _CRASH_RE.search(line)
    if not m:
        return None
    return {"jerk_mg": int(m.group(1)), "accel": {"x": int(m.group(2)), "y": int(m.group(3)), "z": int(m.group(4))}}


def parse_session_started(line: bytes) -> Optional[Dict]:
    m = _STARTED_RE.search(line)
    if not m:
        return None
    return {"duration_s": int(m.group(1)), "rate_hz": int(m.group(2)), "baud": int(m.group(3)) if m.group(3) else None}


def unpack_frames(raw: bytes) -> Tuple[List[Tuple[float, float, float, float]], Dict]:
    """Decode a byte stream into [(t_s, x_g, y_g, z_g)] and quality statistics.

    Resynchronises on the magic bytes after corruption, verifies every checksum, unwraps the
    32-bit microsecond clock and counts packets lost (sequence gaps).
    """
    samples, stats = [], {"packets": 0, "bad_checksum": 0, "resyncs": 0, "lost_packets": 0}
    off, n = 0, len(raw)
    prev_seq, prev_t, wraps = None, None, 0
    while off + PACKET_SIZE <= n:
        if raw[off] != MAGIC_0 or raw[off + 1] != MAGIC_1:
            nxt = raw.find(bytes([MAGIC_0, MAGIC_1]), off + 1)
            if nxt < 0:
                break
            stats["resyncs"] += 1
            off = nxt
            continue
        m0, m1, seq, t_us, x, y, z, crc = struct.unpack_from(PACKET_FORMAT, raw, off)
        if checksum(raw[off:off + PACKET_SIZE - 1]) != crc:
            stats["bad_checksum"] += 1
            off += 1                                   # not a real frame: look for the next magic
            continue
        if prev_seq is not None:
            gap = (seq - prev_seq) & 0xFFFF
            if gap > 1:
                stats["lost_packets"] += gap - 1
        if prev_t is not None and t_us < prev_t - 0x80000000:
            wraps += 1
        prev_seq, prev_t = seq, t_us
        t_s = (t_us + wraps * 0x100000000) / 1e6
        samples.append((t_s, x * SCALE_G_PER_LSB, y * SCALE_G_PER_LSB, z * SCALE_G_PER_LSB))
        stats["packets"] += 1
        off += PACKET_SIZE
    if samples:
        t0 = samples[0][0]
        samples = [(t - t0, x, y, z) for t, x, y, z in samples]
        dts = [b[0] - a[0] for a, b in zip(samples, samples[1:])]
        stats["duration_s"] = round(samples[-1][0], 4)
        stats["mean_rate_hz"] = round((len(samples) - 1) / samples[-1][0], 1) if samples[-1][0] > 0 else 0.0
        stats["max_gap_ms"] = round(max(dts) * 1000, 2) if dts else 0.0
    return samples, stats


def split_capture(buffer: bytes) -> Tuple[bytes, bool]:
    """Binary payload of a capture buffer (text markers removed) and whether ENDED was seen."""
    start = buffer.find(STARTED_MARK)
    body = buffer
    if start >= 0:
        nl = buffer.find(b"\n", start)
        body = buffer[nl + 1:] if nl >= 0 else b""
    end = body.find(ENDED_MARK)
    if end >= 0:
        payload = body[:end]
        if payload.endswith(b"\n"):          # the single newline the ESP prepends to the marker
            payload = payload[:-1]
        return payload, True
    return body, False
