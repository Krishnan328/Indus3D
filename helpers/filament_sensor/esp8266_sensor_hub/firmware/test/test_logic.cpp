// Host-side tests for the firmware's pure logic: serial protocol, rate selection, crash detector.
// Build & run: firmware/test/run.sh
#include <stdio.h>
#include <stdlib.h>
#include "Arduino.h"
#include "config.h"
#include "serial_protocol.h"
#include "crash_detector.h"

uint32_t g_test_millis = 0;
uint32_t millis() { return g_test_millis; }
uint32_t micros() { return g_test_millis * 1000UL; }

static int g_fail = 0, g_run = 0;
#define CHECK(cond) do { ++g_run; if (!(cond)) { ++g_fail; printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)

static bool feed(proto::LineReader& r, const char* s) {
    bool ready = false;
    for (; *s; ++s) ready = r.push(*s);
    return ready;
}

static void test_line_reader() {
    proto::LineReader r;
    CHECK(!feed(r, "RESET_CR"));                     // partial line: not ready, never blocks
    CHECK(feed(r, "ASH\r\n") && strcmp(r.line(), "RESET_CRASH") == 0);
    r.clear();
    CHECK(!feed(r, "\r\n"));                         // empty lines are ignored
    r.clear();
    char big[200]; memset(big, 'A', sizeof(big) - 1); big[sizeof(big) - 1] = 0;
    CHECK(!feed(r, big) && !r.push('\n'));           // overlong line discarded, not executed truncated
    CHECK(feed(r, "PING\n") && strcmp(r.line(), "PING") == 0);   // reader recovers
}

static void test_parser() {
    using namespace proto;
    CHECK(parse("PING").cmd == CMD_PING);
    CHECK(parse("  ping  ").cmd == CMD_PING);        // case-insensitive, trimmed
    CHECK(parse("RESET_CRASH").cmd == CMD_RESET_CRASH);
    CHECK(parse("STATUS").cmd == CMD_STATUS);
    CHECK(parse("").cmd == CMD_NONE && parse("   ").cmd == CMD_NONE && parse(nullptr).cmd == CMD_NONE);
    CHECK(parse("NOPE 1 2").cmd == CMD_UNKNOWN);
    Command c = parse("START_SHAPER 7 1600 921600");
    CHECK(c.cmd == CMD_START_SHAPER && c.has[0] && c.has[1] && c.has[2]);
    CHECK(c.arg[0] == 7 && c.arg[1] == 1600 && c.arg[2] == 921600 && !c.bad_args);
    c = parse("START_SHAPER 7");
    CHECK(c.has[0] && !c.has[1] && !c.has[2]);
    c = parse("START_SHAPER   7    1600");
    CHECK(c.arg[0] == 7 && c.arg[1] == 1600);
    c = parse("START_SHAPER 7 abc");
    CHECK(c.bad_args && c.has[0] && !c.has[1]);
    c = parse("SET_CRASH_THRESHOLD -5");
    CHECK(c.cmd == CMD_SET_CRASH_THRESHOLD && c.arg[0] == -5);
    c = parse("SET_CRASH_THRESHOLD 12x");
    CHECK(c.bad_args && !c.has[0]);
}

static void test_rate_and_baud() {
    const size_t pkt = 15; const double eff = SERIAL_PAYLOAD_EFFICIENCY;
    // 115200 baud = 11520 B/s * 0.85 / 15 = 652 packets/s -> 1600 Hz is impossible, 400 Hz fits
    CHECK(proto::pick_rate(1600, 115200, true, pkt, eff) == 400);
    CHECK(proto::pick_rate(3200, 115200, true, pkt, eff) == 400);
    CHECK(proto::pick_rate(200, 115200, true, pkt, eff) == 200);
    CHECK(proto::pick_rate(1600, 230400, true, pkt, eff) == 800);
    CHECK(proto::pick_rate(1600, 460800, true, pkt, eff) == 1600);
    CHECK(proto::pick_rate(3200, 460800, true, pkt, eff) == 1600);   // 2611 packets/s
    CHECK(proto::pick_rate(3200, 921600, true, pkt, eff) == 3200);   // 5222 packets/s
    CHECK(proto::pick_rate(3200, 115200, false, pkt, eff) == 3200);  // TCP: no serial limit
    CHECK(proto::pick_rate(50, 921600, true, pkt, eff) == 200);      // floor
    CHECK(proto::allowed_baud(921600) && proto::allowed_baud(115200) && !proto::allowed_baud(300000));
}

static AccelDataMg S(int x, int y, int z) { AccelDataMg a; a.x = x; a.y = y; a.z = z; return a; }

static void test_crash_detector() {
    g_test_millis = 100;                              // within the first seconds after boot
    CrashDetector d(2000);
    CHECK(!d.update(S(-300, -400, -850)));            // first sample only primes the detector
    CHECK(!d.update(S(-305, -395, -848)));
    CHECK(d.getBedTelemetry().current_jerk_mg < 20);
    CHECK(!d.isCrashLatched());

    g_test_millis = 200;
    CHECK(d.update(S(-300, 1900, -850)));             // 2295 mg step: crash, even 200 ms after boot
    CHECK(d.isCrashLatched());
    CHECK(d.getLastCrashEvent().jerk_mg >= 2290 && d.getLastCrashEvent().jerk_mg <= 2300);

    g_test_millis = 300;                              // another spike inside the cooldown
    CHECK(!d.update(S(-300, -400, -850)));            // no second report ...
    CHECK(d.isCrashLatched());                        // ... but the latch stays set until acknowledged

    g_test_millis = 300 + CRASH_COOLDOWN_MS + 1;
    d.update(S(-300, -400, -850));
    CHECK(d.update(S(-300, 2000, -850)));             // after the cooldown a new event is reported
}

static void test_crash_reset_and_threshold() {
    g_test_millis = 10000;
    CrashDetector d(2000);
    d.update(S(0, 0, -1000));
    CHECK(d.update(S(0, 3000, -1000)));
    d.resetCrash();
    CHECK(!d.isCrashLatched());
    g_test_millis = 10010;                            // right after the operator reset: report at once
    d.update(S(0, 0, -1000));
    CHECK(d.update(S(0, 3000, -1000)));

    d.resetCrash();
    d.setThreshold(5000);
    g_test_millis = 30000;
    d.update(S(0, 0, -1000));
    CHECK(!d.update(S(0, 3000, -1000)));              // 3000 mg < 5000 mg threshold
    CHECK(d.getThreshold() == 5000);
}

int main() {
    test_line_reader();
    test_parser();
    test_rate_and_baud();
    test_crash_detector();
    test_crash_reset_and_threshold();
    printf("%d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
