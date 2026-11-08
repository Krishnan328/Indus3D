import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import * as T from "./thermalLogic.js";
import { createThermalSlice } from "./thermalSlice.js";

const STATUS = {
  ok: true, ts: 1,
  capabilities: {
    heaters: ["extruder", "heater_bed", "heater_generic chamber"],
    temperature_sensors: ["temperature_sensor mcu", "temperature_fan pi_fan"],
    fans: ["fan", "heater_fan hotend_fan"],
  },
  status: {
    extruder: { temperature: 215.4, target: 220, power: 0.5 },
    heater_bed: { temperature: 60, target: 60, power: 0.1 },
    "heater_generic chamber": { temperature: 35, target: 40, power: 0 },
    "temperature_sensor mcu": { temperature: 41.2 },
    "temperature_fan pi_fan": { temperature: 45, target: 50, speed: 0.3 },
    fan: { speed: 0.8 }, "heater_fan hotend_fan": { speed: 1 },
  },
};

// ── catalogue ─────────────────────────────────────────────────────────────────
test("catalogue: every heater, sensor and fan from Klipper's status becomes a series", () => {
  const cat = T.seriesCatalog(STATUS, null);
  const ids = cat.map((d) => d.id);
  for (const id of ["extruder", "extruder.target", "extruder.power", "heater_bed", "heater_generic chamber",
    "heater_generic chamber.target", "temperature_sensor mcu", "temperature_fan pi_fan", "temperature_fan pi_fan.target",
    "temperature_fan pi_fan.speed", "fan.speed", "heater_fan hotend_fan.speed"]) assert.ok(ids.includes(id), id);
  const by = Object.fromEntries(cat.map((d) => [d.id, d]));
  assert.equal(by["extruder.target"].dashed, true);
  assert.equal(by["extruder.target"].parent, "extruder");
  assert.equal(by["extruder.power"].axis, "pct");
  assert.equal(by.extruder.axis, "temp");
  assert.equal(by["fan.speed"].group, "fan");
  assert.equal(by["heater_generic chamber"].label, "Chamber");
  assert.equal(by.heater_bed.label, "Bed");
});

test("catalogue: hub chamber is added only when Klipper has no chamber sensor", () => {
  const env = { temperature: 29, humidity: 41, available: true };
  assert.ok(T.seriesCatalog(STATUS, env).every((d) => d.id !== T.HUB_CHAMBER));          // heater_generic chamber exists
  const noChamber = { ...STATUS, capabilities: { ...STATUS.capabilities, heaters: ["extruder", "heater_bed"] } };
  const cat = T.seriesCatalog(noChamber, env);
  assert.ok(cat.some((d) => d.id === T.HUB_CHAMBER));
  assert.ok(cat.some((d) => d.id === T.HUB_HUMIDITY && d.group === "humidity" && d.axis === "pct"));
  assert.ok(T.seriesCatalog(noChamber, { temperature: 0, available: false }).every((d) => d.id !== T.HUB_CHAMBER));
  assert.deepEqual(T.seriesCatalog({ ok: false, status: {}, capabilities: {} }, null), []);
});

test("visibility: overlays are opt-in, hidden wins", () => {
  const cat = T.seriesCatalog(STATUS, null);
  const get = (id) => cat.find((d) => d.id === id);
  assert.equal(T.isVisible(get("extruder"), {}, {}), true);
  assert.equal(T.isVisible(get("extruder.target"), {}, {}), true);
  assert.equal(T.isVisible(get("extruder.power"), {}, {}), false);
  assert.equal(T.isVisible(get("extruder.power"), {}, { power: true }), true);
  assert.equal(T.isVisible(get("fan.speed"), {}, {}), false);
  assert.equal(T.isVisible(get("fan.speed"), {}, { fans: true }), true);
  assert.equal(T.isVisible(get("extruder"), { extruder: true }, {}), false);
  assert.equal(T.isVisible({ id: T.HUB_HUMIDITY, group: "humidity" }, {}, {}), false);
  assert.equal(T.isVisible({ id: T.HUB_HUMIDITY, group: "humidity" }, {}, { humidity: true }), true);
});

test("history-only hub series still get a definition", () => {
  const base = T.fallbackCatalog().filter((d) => d.id !== T.HUB_CHAMBER);
  const out = T.withHistoryDefs(base, ["extruder", T.HUB_CHAMBER, T.HUB_HUMIDITY]);
  assert.ok(out.some((d) => d.id === T.HUB_CHAMBER) && out.some((d) => d.id === T.HUB_HUMIDITY));
  assert.equal(T.withHistoryDefs(out, [T.HUB_CHAMBER]).length, out.length);
});

// ── colours ───────────────────────────────────────────────────────────────────
test("colours: user choice wins, known series are fixed, targets share the parent's colour", () => {
  assert.equal(T.colorFor("extruder", {}, 5), "#f97316");
  assert.equal(T.colorFor("extruder", { extruder: "#123456" }, 5), "#123456");
  assert.equal(T.colorFor("extruder.target", { extruder: "#123456" }, 0), "#123456");
  assert.equal(T.colorFor("extruder.target", { "extruder.target": "#abcdef", extruder: "#123456" }, 0), "#abcdef");
  assert.equal(T.colorFor("temperature_sensor mcu", {}, 0), "#f97316");
  assert.notEqual(T.colorFor("temperature_sensor mcu", {}, 1), T.colorFor("temperature_sensor mcu", {}, 2));
  assert.equal(T.colorFor("temperature_sensor mcu", {}, 12), T.colorFor("temperature_sensor mcu", {}, 0));   // palette wraps
});

test("labels read well", () => {
  assert.equal(T.labelFor("extruder1"), "Extruder 1");
  assert.equal(T.labelFor("temperature_sensor raspberry_pi"), "Raspberry pi");
  assert.equal(T.labelFor("fan"), "Part fan");
  assert.equal(T.labelFor("fan_generic exhaust"), "Exhaust");
});

// ── samples ───────────────────────────────────────────────────────────────────
test("live sample: temperature, target, power and speed as percent", () => {
  const s = T.liveSample(STATUS, { temperature: 29, humidity: 41, available: true });
  assert.equal(s.extruder, 215.4);
  assert.equal(s["extruder.target"], 220);
  assert.equal(s["extruder.power"], 50);
  assert.equal(s["fan.speed"], 80);
  assert.equal(s["temperature_fan pi_fan.speed"], 30);
  assert.equal(s[T.HUB_CHAMBER], 29);
  assert.equal(s[T.HUB_HUMIDITY], 41);
  assert.equal(T.liveSample({ status: { x: null, y: "bad" } }, null) && Object.keys(T.liveSample({ status: { x: null, y: "bad" } }, null)).length, 0);
  assert.equal(T.HUB_CHAMBER in T.liveSample(STATUS, { temperature: 0, available: false }), false);
});

test("appendSample keeps a bounded window, replaces near-duplicate stamps and never mutates", () => {
  let buf = {};
  buf = T.appendSample(buf, { a: 1 }, 100);
  const first = buf;
  buf = T.appendSample(buf, { a: 2, b: 5 }, 103);
  assert.deepEqual(first.a, { t: [100], v: [1] });                                  // untouched
  assert.deepEqual(buf.a, { t: [100, 103], v: [1, 2] });
  buf = T.appendSample(buf, { a: 3 }, 103.2);                                       // within 0.5 s: replaces
  assert.deepEqual(buf.a, { t: [100, 103.2], v: [1, 3] });
  buf = T.appendSample(buf, { a: 4 }, 500, 300);                                    // 100 and 103 fall out of the 300 s window
  assert.deepEqual(buf.a, { t: [500], v: [4] });
  assert.deepEqual(T.appendSample({}, { a: NaN, b: undefined }, 1), {});
});

test("fallback samples come from the websocket history", () => {
  const h = [{ ts: 1000, extruder: 200, bed: 60, chamber: 0 }, { ts: 2000, extruder: 201, bed: 60, chamber: 30 }];
  const s = T.fallbackSamples(h, 210, 65);
  assert.deepEqual(s.extruder, { t: [1, 2], v: [200, 201] });
  assert.deepEqual(s[T.HUB_CHAMBER], { t: [2], v: [30] });                           // 0 means "no sensor"
  assert.deepEqual(s["extruder.target"], { t: [2], v: [210] });
  assert.deepEqual(T.fallbackSamples([], 1, 1), {});
});

test("history response: power and fan speed become percent, targets stay degrees", () => {
  const s = T.historyToSeries({ series: {
    extruder: { t: [1, 2], v: [200, 201] }, "extruder.power": { t: [1, 2], v: [0.5, null] },
    "temperature_fan x.speed": { t: [1], v: [0.25] }, junk: "no", short: { t: [1] },
  } });
  assert.deepEqual(s.extruder.v, [200, 201]);
  assert.deepEqual(s["extruder.power"].v, [50, null]);
  assert.deepEqual(s["temperature_fan x.speed"].v, [25]);
  assert.equal(s.junk, undefined);
  assert.deepEqual(T.historyToSeries(null), {});
});

test("merge: live points replace the backfill from their first timestamp on", () => {
  const back = { a: { t: [1, 2, 3, 4], v: [10, 20, 30, 40] }, only: { t: [1], v: [1] } };
  const live = { a: { t: [3.5, 5], v: [35, 50] }, fresh: { t: [5], v: [9] } };
  const m = T.mergeSeries(back, live);
  assert.deepEqual(m.a, { t: [1, 2, 3, 3.5, 5], v: [10, 20, 30, 35, 50] });
  assert.deepEqual(m.only, back.only);
  assert.deepEqual(m.fresh, live.fresh);
  assert.deepEqual(T.mergeSeries({ a: { t: [1, 2], v: [1, 2] } }, { a: { t: [], v: [] } }).a, { t: [1, 2], v: [1, 2] });
});

// ── smoothing, clipping, alignment ──────────────────────────────────────────────
test("smoothing is a trailing moving average over the window", () => {
  const s = { t: [0, 1, 2, 3, 4, 5], v: [0, 10, 20, 30, 40, 50] };
  assert.equal(T.smooth(s, 0), s);
  assert.equal(T.smooth(s, 1), s);
  assert.deepEqual(T.smooth(s, 2).v, [0, 5, 10, 20, 30, 40]);                       // window 2 s = up to 3 samples
  assert.deepEqual(T.smooth(s, 100).v, [0, 5, 10, 15, 20, 25]);
  assert.deepEqual(T.smooth(s, 2).t, s.t);
  assert.equal(T.smooth(undefined, 5), undefined);
  assert.deepEqual(T.smooth({ t: [], v: [] }, 5), { t: [], v: [] });
});

test("clip keeps the last span", () => {
  const s = { t: [1, 2, 3, 4, 5], v: [1, 2, 3, 4, 5] };
  assert.deepEqual(T.clip(s, 5, 2), { t: [3, 4, 5], v: [3, 4, 5] });
  assert.equal(T.clip(s, 5, 100), s);
  assert.deepEqual(T.clip(s, 500, 2), { t: [], v: [] });
});

test("align builds one x axis with nulls where a series has no sample", () => {
  const { x, ys } = T.align({ a: { t: [1, 3], v: [10, 30] }, b: { t: [2, 3], v: [20, 31] } }, ["a", "b", "missing"]);
  assert.deepEqual(x, [1, 2, 3]);
  assert.deepEqual(ys, [[10, null, 30], [null, 20, 31], [null, null, null]]);
  assert.deepEqual(T.align({}, []), { x: [], ys: [] });
});

test("temperature ceiling rounds up to 25 with a floor of 50", () => {
  assert.equal(T.tempCeiling([[20, 30, null]]), 50);
  assert.equal(T.tempCeiling([[20, 226, null], [100]]), 250);
  assert.equal(T.tempCeiling([[250]]), 250);
  assert.equal(T.tempCeiling([]), 50);
});

test("range and smoothing options match the spec", () => {
  assert.deepEqual(T.RANGES.map((r) => r.minutes), [1, 60, 360, 1440]);
  assert.equal(T.RANGES[0].live, true);
  assert.deepEqual(T.SMOOTHING_OPTIONS, [0, 1, 3, 5, 10, 15, 30]);
});

// ── readings and sensors ───────────────────────────────────────────────────────
test("readings and sparklines", () => {
  assert.equal(T.formatReading(215.43, 220), "215.4° → 220°");
  assert.equal(T.formatReading(30, 0), "30.0°");
  assert.equal(T.formatReading(undefined, 5), "—");
  assert.equal(T.sparklinePoints([1]), "");
  assert.equal(T.sparklinePoints([]), "");
  const pts = T.sparklinePoints([0, 5, 10], 100, 20).split(" ");
  assert.equal(pts.length, 3);
  assert.equal(pts[0], "1.0,19.0");
  assert.equal(pts[2], "99.0,1.0");
  assert.equal(T.sparklinePoints([3, 3, 3], 10, 10), "1.0,5.0 5.0,5.0 9.0,5.0");
  assert.ok(!T.sparklinePoints([1, NaN, 3]).includes("NaN"));
});

test("sensor parameters: units from parameter_info or by name, values formatted", () => {
  const params = T.sensorParameters({
    values: { temperature: 31.24, humidity: 44, pressure: 1005.3 },
    parameter_info: [{ units: "°C" }, { units: "%" }], history: { temperature: [1, 2] },
  });
  assert.deepEqual(params.map((p) => [p.key, p.unit]), [["temperature", "°C"], ["humidity", "%"], ["pressure", "hPa"]]);
  assert.deepEqual(params[0].history, [1, 2]);
  assert.equal(T.formatSensorValue(31.24, "°C"), "31.2 °C");
  assert.equal(T.formatSensorValue(1005.3, "hPa"), "1005 hPa");
  assert.equal(T.formatSensorValue(null, "x"), "—");
  assert.equal(T.formatSensorValue("on", ""), "on");
  assert.deepEqual(T.sensorParameters(null), []);
  // Flask sorts JSON keys: Moonraker's original order (keys) keeps temperature first and pairs the right unit
  const sorted = T.sensorParameters({ values: { humidity: 44, temperature: 31.2 }, keys: ["temperature", "humidity"],
    parameter_info: [{ units: "degC" }, { units: "pct" }] });
  assert.deepEqual(sorted.map((p) => p.key), ["temperature", "humidity"]);
  assert.equal(sorted[0].unit, "°C");
  const custom = T.sensorParameters({ values: { gas: 5, zeta: 2 }, keys: ["zeta", "gas"], parameter_info: [{ units: "kPa" }, { units: "ppm" }] });
  assert.deepEqual(custom.map((p) => [p.key, p.unit]), [["zeta", "kPa"], ["gas", "Ω"]]);
});

// ── slice ─────────────────────────────────────────────────────────────────────
function makeStore(initial = {}) {
  let state = { ...initial };
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = { ...state, ...createThermalSlice(set, get, () => "http://api") };
  return { get };
}
const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
let calls; let responder;
beforeEach(() => {
  calls = [];
  globalThis.fetch = async (url, opts) => { calls.push({ url, opts }); return responder(url, opts); };
});

test("slice: recordThermalSample appends only while Klipper status is available", () => {
  const s = makeStore({ printerStatus: STATUS, environment: {}, uiPrefs: {} });
  s.get().recordThermalSample();
  assert.equal(s.get().thermalLive.extruder.v.length, 1);
  assert.equal(s.get().thermalLive["extruder.power"].v[0], 50);
  const off = makeStore({ printerStatus: { ok: false, status: {} }, environment: {}, uiPrefs: {} });
  off.get().recordThermalSample();
  assert.deepEqual(off.get().thermalLive, {});
});

test("slice: history fetch stores converted series; the latest request wins", async () => {
  const s = makeStore({ uiPrefs: {} });
  let release;
  responder = (url) => url.includes("minutes=60")
    ? new Promise((r) => { release = () => r(json(200, { ok: true, now: 9, series: { extruder: { t: [1], v: [1] } }, sources: { moonraker: { ok: true } }, chamber_source: null })); })
    : json(200, { ok: true, now: 10, series: { extruder: { t: [2], v: [2] }, "extruder.power": { t: [2], v: [0.5] } }, sources: {}, chamber_source: "esp_bed_hub" });
  const slow = s.get().fetchThermalHistory(60);
  await s.get().fetchThermalHistory(1);
  release(); await slow;
  const h = s.get().thermalHistory;
  assert.equal(h.minutes, 1);
  assert.deepEqual(h.series["extruder.power"].v, [50]);
  assert.equal(h.chamberSource, "esp_bed_hub");
  assert.equal(h.loading, false);
  assert.match(calls[0].url, /\/api\/v1\/printer\/thermal_history\?minutes=60/);
});

test("slice: history errors are kept as a message", async () => {
  const s = makeStore({ uiPrefs: {} });
  responder = () => json(502, { ok: false, error: "Moonraker unreachable", sources: { moonraker: { ok: false } } });
  await s.get().fetchThermalHistory(360);
  assert.equal(s.get().thermalHistory.error, "Moonraker unreachable");
  assert.deepEqual(s.get().thermalHistory.series, {});
  responder = () => { throw new Error("offline"); };
  await s.get().fetchThermalHistory(360);
  assert.match(s.get().thermalHistory.error, /offline/);
});

test("slice: sensors", async () => {
  const s = makeStore({ uiPrefs: {} });
  responder = () => json(200, { ok: true, sensors: [{ id: "bed_hub" }] });
  await s.get().fetchMoonrakerSensors();
  assert.equal(s.get().thermalSensors.sensors[0].id, "bed_hub");
  responder = () => json(502, { ok: false, error: "Moonraker unreachable" });
  await s.get().fetchMoonrakerSensors();
  assert.equal(s.get().thermalSensors.ok, false);
  assert.equal(s.get().thermalSensors.sensors.length, 1);                            // last data kept
  assert.equal(s.get().thermalSensors.error, "Moonraker unreachable");
});

test("slice: colours persist through uiPrefs and are mirrored to the server preferences", () => {
  const synced = [];
  const prefs = {};
  const s = makeStore({ uiPrefs: { chartColors: {} }, setUiPref: (k, v) => { prefs[k] = v; s.get().uiPrefs[k] = v; }, syncPreference: (k, v) => synced.push([k, v]) });
  s.get().setChartColor("extruder", "#ff0000");
  assert.deepEqual(prefs.chartColors, { extruder: "#ff0000" });
  assert.deepEqual(synced[0], ["chartColors", JSON.stringify({ extruder: "#ff0000" })]);
  s.get().setChartColor("extruder", null);                                           // reset
  assert.deepEqual(prefs.chartColors, {});
});

test("slice: restoreChartColors takes the server's colours once, and only when none are stored locally", async () => {
  const prefs = {};
  responder = () => json(200, { theme: "classic", chartColors: JSON.stringify({ heater_bed: "#00ff00" }) });
  const s = makeStore({ uiPrefs: { chartColors: {} }, setUiPref: (k, v) => { prefs[k] = v; } });
  await s.get().restoreChartColors();
  await s.get().restoreChartColors();
  assert.deepEqual(prefs.chartColors, { heater_bed: "#00ff00" });
  assert.equal(calls.length, 1);
  const local = makeStore({ uiPrefs: { chartColors: { a: "#111111" } }, setUiPref: () => { throw new Error("must not overwrite"); } });
  calls.length = 0;
  await local.get().restoreChartColors();
  assert.equal(calls.length, 0);
});
