#pragma once
// Serial command protocol of the bed sensor hub: a non-blocking line reader and a
// parser. Deliberately free of Arduino types so it is unit-tested on the host
// (firmware/test/run.sh).
//
//   PING                              -> PONG
//   STATUS                            -> "// STATUS: ..." one-liner
//   START_SHAPER [dur_s] [rate_hz] [baud]
//   STOP_SHAPER
//   SET_CRASH_THRESHOLD <mg>
//   RESET_CRASH                       -> clears the crash latch
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

namespace proto {

enum Cmd : uint8_t {
    CMD_NONE = 0,
    CMD_PING,
    CMD_STATUS,
    CMD_START_SHAPER,
    CMD_STOP_SHAPER,
    CMD_SET_CRASH_THRESHOLD,
    CMD_RESET_CRASH,
    CMD_UNKNOWN,
};

struct Command {
    Cmd  cmd;
    long arg[3];
    bool has[3];
    bool bad_args;      // an argument was present but not a plain integer
    Command() : cmd(CMD_NONE), bad_args(false) {
        for (int i = 0; i < 3; ++i) { arg[i] = 0; has[i] = false; }
    }
};

// Accumulates characters until '\n'. Never blocks (unlike Serial.readStringUntil, which waits
// up to a second for a missing newline and stalls the 200 Hz crash-detection loop). A line
// longer than the buffer is discarded whole instead of being executed truncated.
class LineReader {
public:
    static const size_t CAP = 96;
    LineReader() { clear(); }

    // Feed one character; true when a complete, non-overflowed, non-empty line is ready.
    bool push(char ch) {
        if (ch == '\r') return false;
        if (ch == '\n') {
            bool ok = !_overflow && _len > 0;
            _buf[_len] = '\0';
            _ready = ok;
            if (!ok) { _len = 0; _overflow = false; }
            return ok;
        }
        if (_len + 1 >= CAP) { _overflow = true; return false; }
        _buf[_len++] = ch;
        return false;
    }
    const char* line() const { return _buf; }
    void clear() { _len = 0; _overflow = false; _ready = false; _buf[0] = '\0'; }

private:
    char   _buf[CAP];
    size_t _len;
    bool   _overflow;
    bool   _ready;
};

inline bool ieq(const char* a, const char* b) {
    for (; *a && *b; ++a, ++b) {
        char x = (*a >= 'a' && *a <= 'z') ? (char)(*a - 32) : *a;
        char y = (*b >= 'a' && *b <= 'z') ? (char)(*b - 32) : *b;
        if (x != y) return false;
    }
    return *a == *b;
}

// Parse "WORD [int] [int] [int]". Unknown words -> CMD_UNKNOWN, empty -> CMD_NONE.
inline Command parse(const char* line) {
    Command c;
    char buf[LineReader::CAP];
    strncpy(buf, line ? line : "", sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char* save = nullptr;
    char* word = nullptr;
    // tiny strtok_r replacement (not every embedded libc ships one)
    char* p = buf;
    while (*p == ' ' || *p == '\t') ++p;
    if (*p == '\0') return c;
    word = p;
    while (*p && *p != ' ' && *p != '\t') ++p;
    if (*p) { *p++ = '\0'; }
    save = p;

    if (ieq(word, "PING"))                     c.cmd = CMD_PING;
    else if (ieq(word, "STATUS"))              c.cmd = CMD_STATUS;
    else if (ieq(word, "START_SHAPER"))        c.cmd = CMD_START_SHAPER;
    else if (ieq(word, "STOP_SHAPER"))         c.cmd = CMD_STOP_SHAPER;
    else if (ieq(word, "SET_CRASH_THRESHOLD")) c.cmd = CMD_SET_CRASH_THRESHOLD;
    else if (ieq(word, "RESET_CRASH"))         c.cmd = CMD_RESET_CRASH;
    else { c.cmd = CMD_UNKNOWN; return c; }

    int n = 0;
    p = save;
    while (*p && n < 3) {
        while (*p == ' ' || *p == '\t') ++p;
        if (!*p) break;
        char* tok = p;
        while (*p && *p != ' ' && *p != '\t') ++p;
        if (*p) *p++ = '\0';
        char* end = nullptr;
        long v = strtol(tok, &end, 10);
        if (end == tok || *end != '\0') { c.bad_args = true; ++n; continue; }
        c.arg[n] = v;
        c.has[n] = true;
        ++n;
    }
    return c;
}

inline bool allowed_baud(uint32_t baud) {
    return baud == 115200 || baud == 230400 || baud == 460800 || baud == 921600;
}

// Largest supported ADXL rate <= `requested` that a serial link of `baud` can carry with
// `packet_bytes`-byte packets (8N1 = baud/10 bytes per second, derated by `efficiency`).
// Over TCP there is no such limit. Never returns less than 200 Hz.
inline uint16_t pick_rate(uint16_t requested, uint32_t baud, bool over_serial,
                          size_t packet_bytes, double efficiency) {
    static const uint16_t kRates[] = {3200, 1600, 800, 400, 200};
    uint32_t capacity = over_serial
        ? (uint32_t)((baud / 10.0) * efficiency / (double)packet_bytes)
        : 0xFFFFFFFFUL;
    for (size_t i = 0; i < sizeof(kRates) / sizeof(kRates[0]); ++i) {
        if (kRates[i] <= requested && kRates[i] <= capacity) return kRates[i];
    }
    return 200;
}

}  // namespace proto
