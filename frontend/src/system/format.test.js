import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtKb, fmtUptime, fmtNum, fmtRate, fmtMhz, tone, visibleAlerts, printBusyState } from "./format.js";

test("memory, uptime, rates and clocks read naturally and never show NaN", () => {
  assert.equal(fmtKb(3885000), "3.7 GB");
  assert.equal(fmtKb(2048), "2 MB");
  assert.equal(fmtKb(500), "500 kB");
  assert.equal(fmtKb(null), "—");
  assert.equal(fmtUptime(187432), "2d 4h");
  assert.equal(fmtUptime(3700), "1h 1m");
  assert.equal(fmtUptime(90), "1m");
  assert.equal(fmtUptime(undefined), "—");
  assert.equal(fmtNum(51.234, 1, "°C"), "51.2°C");
  assert.equal(fmtNum(NaN), "—");
  assert.equal(fmtRate(4455.9), "4.4 kB/s");
  assert.equal(fmtRate(12), "12 B/s");
  assert.equal(fmtMhz(180000000), "180 MHz");
  assert.equal(fmtMhz(12000000), "12.0 MHz");
});

test("tone picks a warning colour from thresholds", () => {
  assert.equal(tone(50, 70, 80), "");
  assert.equal(tone(75, 70, 80), "text-amber-500");
  assert.equal(tone(85, 70, 80), "text-red-500");
  assert.equal(tone(undefined, 70, 80), "");
});

test("alerts: most severe first, dismissed info is hidden, critical cannot be dismissed", () => {
  const alerts = [
    { id: "i", severity: "info" }, { id: "c", severity: "critical" }, { id: "w", severity: "warning" },
    { id: "i2", severity: "info" },
  ];
  assert.deepEqual(visibleAlerts(alerts, {}).map((a) => a.id), ["c", "w", "i", "i2"]);
  assert.deepEqual(visibleAlerts(alerts, { i: true, c: true }).map((a) => a.id), ["c", "w", "i2"]);
  assert.deepEqual(visibleAlerts(undefined, undefined), []);
});

test("print busy states", () => {
  assert.ok(printBusyState("printing") && printBusyState("paused"));
  assert.ok(!printBusyState("standby") && !printBusyState(undefined));
});
