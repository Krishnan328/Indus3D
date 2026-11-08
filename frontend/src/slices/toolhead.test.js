import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createToolheadSlice } from "./toolheadSlice.js";
import { createUiPrefsSlice, loadUiPrefs, mergePrefs, UI_PREF_DEFAULTS } from "./uiPrefsSlice.js";
import * as L from "./toolheadLogic.js";

function makeStore(factory, initial = {}) {
  let state = { ...initial };
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = { ...state, ...factory(set, get, () => "http://api") };
  return { get, set };
}
const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

let calls; let responder; let confirmAnswer;
beforeEach(() => {
  calls = [];
  confirmAnswer = true;
  globalThis.window = { confirm: () => confirmAnswer };
  globalThis.fetch = async (url, opts) => { calls.push({ url, body: JSON.parse(opts.body || "{}"), opts }); return responder(url, opts); };
  responder = () => json(200, { status: "ok" });
});
const store = () => makeStore((set, get, api) => createToolheadSlice(set, get, api));

// ── slice ─────────────────────────────────────────────────────────────────────
test("typed actions post values and names (never G-code) to /printer/adjust/<control>", async () => {
  const s = store();
  await s.get().setHeaterTarget("extruder", 215);
  await s.get().setFanSpeed("fan", 0.5);
  await s.get().setOutputPin("output_pin beeper", 1);
  await s.get().setSpeedFactor(120);
  await s.get().setFlowFactor(95);
  await s.get().setPressureAdvance(0.04);
  await s.get().setPressureAdvance(0.04, 0.03);
  await s.get().setRetraction({ retract_length: 0.8 });
  await s.get().babystepZ(-0.025);
  await s.get().motorsOff();
  await s.get().levelAction("TESTZ", { z: -0.1 });
  await s.get().extrude(10, 300);
  await s.get().extrude(-5);
  assert.deepEqual(calls.map((c) => [c.url.replace("http://api/api/v1/printer/adjust/", ""), c.body]), [
    ["heater", { heater: "extruder", target: 215 }], ["fan", { fan: "fan", speed: 0.5 }],
    ["output_pin", { pin: "output_pin beeper", value: 1 }], ["speed", { factor: 120 }], ["flow", { factor: 95 }],
    ["pressure_advance", { advance: 0.04 }], ["pressure_advance", { advance: 0.04, smooth_time: 0.03 }],
    ["retraction", { retract_length: 0.8 }], ["babystep", { step: -0.025 }], ["motors_off", {}],
    ["level", { action: "TESTZ", z: -0.1 }], ["extrude", { amount: 10, feedrate: 300 }], ["extrude", { amount: -5 }],
  ]);
  assert.ok(calls.every((c) => !JSON.stringify(c.body).match(/command|gcode|script/i)));
});

test("a successful action sets a status note; server errors and 429 are reported, not thrown", async () => {
  const s = store();
  assert.equal((await s.get().setSpeedFactor(110)).ok, true);
  assert.equal(s.get().toolheadStatus.ok, true);
  responder = () => json(409, { error: "The extruder is below its minimum extrusion temperature" });
  const r = await s.get().extrude(5, 300);
  assert.equal(r.ok, false);
  assert.equal(r.status, 409);
  assert.match(s.get().toolheadStatus.message, /minimum extrusion/);
  responder = () => json(429, { error: "rate limited" });
  assert.match((await s.get().setFlowFactor(100)).message, /slow down/i);
  responder = () => json(502, { error: "Moonraker unreachable: down" });
  assert.match((await s.get().setHeaterTarget("heater_bed", 60)).message, /unreachable/);
  responder = () => { throw new Error("offline"); };
  const off = await s.get().motorsOff();
  assert.equal(off.ok, false);
  assert.match(off.message, /offline/);
});

test("saving the Z offset asks first, sends confirmed=true and reports the SAVE_CONFIG requirement", async () => {
  const s = store();
  confirmAnswer = false;
  assert.equal((await s.get().saveZOffset("probe")).message, "cancelled");
  assert.equal(calls.length, 0);
  confirmAnswer = true;
  responder = () => json(200, { status: "ok", restart_required: true, message: "Run SAVE_CONFIG to make it permanent." });
  const r = await s.get().saveZOffset("endstop");
  assert.deepEqual(calls[0].body, { target: "endstop", confirmed: true });
  assert.match(r.message, /SAVE_CONFIG/);
});

test("homeSelected sends the axes and a bare body for all axes", async () => {
  const s = store();
  await s.get().homeSelected("XY");
  await s.get().homeSelected();
  assert.equal(calls[0].url, "http://api/api/v1/printer/home");
  assert.deepEqual([calls[0].body, calls[1].body], [{ axes: "XY" }, {}]);
  responder = () => json(409, { error: "Cannot home while a print is active" });
  assert.equal((await s.get().homeSelected("Z")).ok, false);
});

// ── logic ─────────────────────────────────────────────────────────────────────
test("heater ceiling is max_temp minus the margin and setpoints are clamped to it", () => {
  const limits = { extruder: { max_temp: 285 }, "heater_generic chamber": { max_temp: 70 } };
  assert.equal(L.heaterCeiling(limits, "extruder"), 280);
  assert.equal(L.heaterCeiling(limits, "heater_generic Chamber"), 65);
  assert.equal(L.heaterCeiling(limits, "heater_bed"), null);
  assert.equal(L.parseSetpoint("215", 280), 215);
  assert.equal(L.parseSetpoint("999", 280), 280);
  assert.equal(L.parseSetpoint("-5", 280), 0);
  assert.equal(L.parseSetpoint("60,5", 120), 60.5);
  assert.equal(L.parseSetpoint("abc", 120), null);
  assert.equal(L.parseSetpoint("", 120), null);
});

test("feedrate, percent and babystep helpers stay inside the server's bounds", () => {
  assert.equal(L.feedrateFromSpeed(5), 300);
  assert.equal(L.feedrateFromSpeed(0.1), 30);
  assert.equal(L.feedrateFromSpeed(500), 3000);
  assert.equal(L.toPercent(0.5), 50);
  assert.equal(L.fromPercent(150), 1);
  assert.equal(L.toPercent(undefined), 0);
  assert.equal(L.formatStep(0.025), "+0.025");
  assert.equal(L.formatStep(-0.1), "-0.1");
  assert.deepEqual(L.cleanIncrements([0.1, 0.01, 0.01, 0, -1, 2, "x"]), [0.01, 0.1]);
  assert.deepEqual(L.cleanIncrements([], [0.5]), [0.5]);
  assert.deepEqual(L.parseNumberList("0.5, 2, x, -1, 500", { min: 0, max: 100 }), [0.5, 2]);
  assert.equal(L.zOffsetOf({ gcode_move: { homing_origin: [0, 0, -0.12, 0] } }), -0.12);
  assert.equal(L.zOffsetOf({}), null);
});

test("controls are disabled with a reason during a print, when cold, or without the capability", () => {
  const base = { printing: false, capabilities: {}, status: {}, connected: true };
  assert.equal(L.reasonDisabled("motion", base), null);
  assert.match(L.reasonDisabled("motion", { ...base, printing: true }), /print/);
  assert.match(L.reasonDisabled("level", { ...base, printing: true }), /print/);
  assert.match(L.reasonDisabled("motors_off", { ...base, printing: true }), /print/);
  assert.match(L.reasonDisabled("extrude", { ...base, status: { extruder: { can_extrude: false } } }), /cold/i);
  assert.equal(L.reasonDisabled("extrude", { ...base, status: { extruder: { can_extrude: true } } }), null);
  assert.match(L.reasonDisabled("retraction", base), /firmware_retraction/);
  assert.equal(L.reasonDisabled("retraction", { ...base, capabilities: { firmware_retraction: true } }), null);
  assert.match(L.reasonDisabled("save_probe", base), /probe/i);
  assert.match(L.reasonDisabled("motion", { ...base, connected: false }), /unavailable/);
  assert.equal(L.reasonDisabled("babystep", { ...base, printing: true }), null);      // babystepping is for printing
  assert.equal(L.isPrinting("paused"), true);
  assert.equal(L.isPrinting("standby"), false);
});

test("leveling and tool-macro buttons only appear for what the printer has", () => {
  assert.deepEqual(L.levelingActions({}), []);
  assert.deepEqual(L.levelingActions({ z_tilt: true, probe: true }).map((a) => a.action), ["Z_TILT_ADJUST", "PROBE_CALIBRATE"]);
  assert.equal(L.levelingActions({ quad_gantry_level: true, screws_tilt_adjust: true, bed_screws: true }).length, 3);
  const caps = { tool_macros: { load_filament: "LOAD_FILAMENT", unload_filament: null, clean_nozzle: "CLEAN_NOZZLE", park_toolhead: null } };
  assert.deepEqual(L.toolMacroButtons(caps).map((b) => b.macro), ["LOAD_FILAMENT", "CLEAN_NOZZLE"]);
  assert.deepEqual(L.toolMacroButtons({}), []);
  assert.deepEqual(L.controllableFans({ fans: ["fan", "heater_fan hotend_fan", "fan_generic exhaust", "controller_fan x"] }), ["fan", "fan_generic exhaust"]);
  assert.equal(L.primaryExtruder({ extruders: ["extruder1", "extruder"] }), "extruder");
  assert.equal(L.primaryExtruder({}), "extruder");
  assert.equal(L.shortName("heater_generic chamber"), "chamber");
});

test("circle wheel sectors are valid closed paths", () => {
  const d = L.sectorPath(0, 0, 20, 40, 0);
  assert.match(d, /^M-?\d/);
  assert.ok(d.endsWith("Z"));
  assert.equal((d.match(/A/g) || []).length, 2);
  assert.ok(!d.includes("NaN"));
});

// ── ui prefs ──────────────────────────────────────────────────────────────────
test("uiPrefs: defaults exist for every key (a fresh browser must not crash the Control tab)", () => {
  const prefs = loadUiPrefs({ getItem: () => null });
  assert.deepEqual(prefs.moveDistances, [0.1, 1, 10, 50]);
  assert.equal(typeof prefs.toolheadSpeedXY, "number");
  assert.equal(prefs.toolheadStyle, "bars");
  assert.equal(prefs.combinedXYHome, true);
  assert.equal(loadUiPrefs({ getItem: () => "{broken" }).toolheadStyle, "bars");
  assert.equal(loadUiPrefs(null).toolheadStyle, "bars");
});

test("uiPrefs: stored values win, wrong-typed ones fall back, unknown keys survive", () => {
  const prefs = mergePrefs({ toolheadStyle: "circle", moveDistances: "oops", toolheadSpeedXY: 80, futureKey: 1, chartColors: { a: "#fff" } });
  assert.equal(prefs.toolheadStyle, "circle");
  assert.deepEqual(prefs.moveDistances, UI_PREF_DEFAULTS.moveDistances);
  assert.equal(prefs.toolheadSpeedXY, 80);
  assert.equal(prefs.futureKey, 1);
  assert.deepEqual(prefs.chartColors, { a: "#fff" });
  assert.deepEqual(mergePrefs([1, 2]), UI_PREF_DEFAULTS);
});

test("uiPrefs: setUiPref merges into the store and persists", () => {
  const saved = {};
  const storage = { setItem: (k, v) => { saved[k] = v; } };
  const s = makeStore((set, get) => createUiPrefsSlice(set, get, () => storage), { uiPrefs: loadUiPrefs({ getItem: () => null }) });
  s.get().setUiPref("toolheadStyle", "cross");
  assert.equal(s.get().uiPrefs.toolheadStyle, "cross");
  assert.equal(s.get().uiPrefs.moveDistances.length, 4);
  assert.equal(JSON.parse(saved.indus3d_ui_prefs).toolheadStyle, "cross");
  const broken = makeStore((set, get) => createUiPrefsSlice(set, get, () => ({ setItem: () => { throw new Error("quota"); } })), { uiPrefs: {} });
  broken.get().setUiPref("a", 1);                                   // private mode: no throw, value kept in memory
  assert.equal(broken.get().uiPrefs.a, 1);
});
