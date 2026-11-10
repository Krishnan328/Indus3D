// Pure logic for the temperature chart and the Sensors card: which series exist (from Klipper's object
// status), how samples are kept, smoothed and aligned for plotting, colours, and sparklines.
// No React, no store, no DOM: everything here is unit-tested in thermal.test.js.

export const RANGES = [
  { id: "1m", label: "1 min", minutes: 1, live: true },
  { id: "1h", label: "1 h", minutes: 60 },
  { id: "6h", label: "6 h", minutes: 360 },
  { id: "24h", label: "24 h", minutes: 1440 },
];
export const SMOOTHING_OPTIONS = [0, 1, 3, 5, 10, 15, 30];          // seconds; 0 = none
export const LIVE_KEEP_S = 300;                                     // live buffer: 5 min (1 min is shown)
export const HUB_CHAMBER = "esp_bed_hub.chamber";
export const HUB_HUMIDITY = "esp_bed_hub.humidity";

const PALETTE = ["#f97316", "#3b82f6", "#22c55e", "#eab308", "#a855f7", "#06b6d4", "#ec4899", "#84cc16",
  "#f43f5e", "#14b8a6", "#8b5cf6", "#fb923c"];
const FIXED = { extruder: "#f97316", heater_bed: "#3b82f6", chamber: "#22c55e", [HUB_CHAMBER]: "#22c55e", [HUB_HUMIDITY]: "#38bdf8" };

const prettify = (text) => text.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function labelFor(object) {
  if (object === "extruder") return "Extruder";
  if (object === "heater_bed") return "Bed";
  if (object === "fan") return "Part fan";
  if (object === HUB_CHAMBER) return "Chamber (hub)";
  if (object === HUB_HUMIDITY) return "Humidity (hub)";
  const m = /^extruder(\d+)$/.exec(object);
  if (m) return `Extruder ${m[1]}`;
  const space = object.indexOf(" ");
  return space < 0 ? prettify(object) : prettify(object.slice(space + 1));
}

// A stable colour per series: well-known ones are fixed, everything else follows the catalogue order.
export function colorFor(id, userColors = {}, index = 0) {
  const base = id.replace(/\.(target|power|speed)$/, "");
  return userColors[id] || userColors[base] || FIXED[base] || PALETTE[index % PALETTE.length];
}

// Series the chart can draw, from the live Klipper status. `group` drives the default visibility and the
// legend; `axis` is "temp" (deg C) or "pct" (0-100, fan speed and heater power overlays).
//   heaters      -> temperature + target (dashed) + power (overlay)
//   sensors      -> temperature_sensor / temperature_fan (+ target, + speed overlay)
//   fans         -> speed overlay
export function seriesCatalog(printerStatus, environment) {
  const caps = printerStatus?.capabilities || {};
  const status = printerStatus?.status || {};
  const out = [];
  const add = (def) => out.push({ axis: "temp", dashed: false, ...def });
  for (const h of caps.heaters || []) {
    add({ id: h, label: labelFor(h), group: "heater", object: h });
    add({ id: `${h}.target`, label: `${labelFor(h)} target`, group: "target", object: h, dashed: true, parent: h });
    add({ id: `${h}.power`, label: `${labelFor(h)} power`, group: "power", axis: "pct", object: h, parent: h });
  }
  for (const s of caps.temperature_sensors || []) {
    add({ id: s, label: labelFor(s), group: "sensor", object: s });
    if (s.startsWith("temperature_fan ")) {
      add({ id: `${s}.target`, label: `${labelFor(s)} target`, group: "target", object: s, dashed: true, parent: s });
      add({ id: `${s}.speed`, label: `${labelFor(s)} fan`, group: "fan", axis: "pct", object: s, parent: s });
    }
  }
  for (const f of caps.fans || []) add({ id: `${f}.speed`, label: labelFor(f), group: "fan", axis: "pct", object: f });
  // Chamber from the ESP8266 hub when Klipper has no chamber sensor of its own
  const klipperChamber = [...(caps.heaters || []), ...(caps.temperature_sensors || [])].some((o) => /chamber/i.test(o));
  if (environment && environment.available !== false && Number(environment.humidity) > 0 && !out.some((d) => d.id === HUB_HUMIDITY)) {
    add({ id: HUB_HUMIDITY, label: labelFor(HUB_HUMIDITY), group: "humidity", axis: "pct", object: null });
  }
  if (!klipperChamber && environment && environment.available !== false && Number(environment.temperature) > 0) {
    add({ id: HUB_CHAMBER, label: labelFor(HUB_CHAMBER), group: "sensor", object: null });
  }
  if (!Object.keys(status).length && !out.length) return [];
  return out;
}

// What the chart shows when Klipper's own status is unavailable (the simulator, or Moonraker briefly down):
// extruder, bed and chamber from the telemetry websocket history.
export function fallbackCatalog() {
  return [
    { id: "extruder", label: "Extruder", group: "heater", axis: "temp", dashed: false },
    { id: "extruder.target", label: "Extruder target", group: "target", axis: "temp", dashed: true, parent: "extruder" },
    { id: "heater_bed", label: "Bed", group: "heater", axis: "temp", dashed: false },
    { id: "heater_bed.target", label: "Bed target", group: "target", axis: "temp", dashed: true, parent: "heater_bed" },
    { id: HUB_CHAMBER, label: "Chamber", group: "sensor", axis: "temp", dashed: false },
  ];
}

// Overlays are opt-in; heaters, targets and sensors show by default.
export function isVisible(def, hidden = {}, overlays = {}) {
  if (hidden[def.id]) return false;
  if (def.group === "fan") return !!overlays.fans;
  if (def.group === "power") return !!overlays.power;
  if (def.group === "humidity") return !!overlays.humidity;
  return true;
}

// One live sample {id: value} from the status snapshot (and the hub chamber when it is a series).
export function liveSample(printerStatus, environment) {
  const out = {};
  for (const [obj, st] of Object.entries(printerStatus?.status || {})) {
    if (!st || typeof st !== "object") continue;
    if (Number.isFinite(st.temperature)) out[obj] = st.temperature;
    if (Number.isFinite(st.target)) out[`${obj}.target`] = st.target;
    if (Number.isFinite(st.power)) out[`${obj}.power`] = st.power * 100;
    if (Number.isFinite(st.speed)) out[`${obj}.speed`] = st.speed * 100;
  }
  if (environment && environment.available !== false && Number(environment.temperature) > 0) {
    out[HUB_CHAMBER] = Number(environment.temperature);
    if (Number(environment.humidity) > 0) out[HUB_HUMIDITY] = Number(environment.humidity);
  }
  return out;
}

// Same, from the telemetry websocket history when Klipper's status is not available.
export function fallbackSamples(history = [], extTarget = 0, bedTarget = 0) {
  const buf = {};
  const push = (id, t, v) => { (buf[id] ||= { t: [], v: [] }); buf[id].t.push(t); buf[id].v.push(v); };
  for (const s of history) {
    const t = s.ts / 1000;
    push("extruder", t, Number(s.extruder) || 0);
    push("heater_bed", t, Number(s.bed) || 0);
    if (Number(s.chamber) > 0) push(HUB_CHAMBER, t, Number(s.chamber));
  }
  const last = history[history.length - 1];
  if (last) {                                    // the websocket history carries no targets: only the current ones are known
    push("extruder.target", last.ts / 1000, Number(extTarget) || 0);
    push("heater_bed.target", last.ts / 1000, Number(bedTarget) || 0);
  }
  return buf;
}

// Append one sample (at time `t` seconds) to per-series buffers {id: {t: [], v: []}}, dropping data older than
// `keepS`. Returns a new object; the input is not mutated. Samples closer than `minGapS` replace the last one.
export function appendSample(buffers, sample, t, keepS = LIVE_KEEP_S, minGapS = 0.5) {
  const out = {};
  for (const [id, series] of Object.entries(buffers)) out[id] = series;
  for (const [id, value] of Object.entries(sample)) {
    if (!Number.isFinite(value)) continue;
    const cur = out[id] || { t: [], v: [] };
    const last = cur.t.length - 1;
    const ts = last >= 0 && t - cur.t[last] < minGapS ? [...cur.t.slice(0, last), t] : [...cur.t, t];
    const vs = last >= 0 && t - cur.t[last] < minGapS ? [...cur.v.slice(0, last), value] : [...cur.v, value];
    let drop = 0;
    while (drop < ts.length && ts[drop] < t - keepS) drop += 1;
    out[id] = drop ? { t: ts.slice(drop), v: vs.slice(drop) } : { t: ts, v: vs };
  }
  return out;
}

// Merge a backfill (older, from /thermal_history) with the live buffer (newer): backfill points that are
// older than the first live point, then every live point.
export function mergeSeries(backfill = {}, live = {}) {
  const out = {};
  for (const id of new Set([...Object.keys(backfill), ...Object.keys(live)])) {
    const b = backfill[id]; const l = live[id];
    if (!b) { out[id] = l; continue; }
    if (!l || !l.t.length) { out[id] = b; continue; }
    const cut = b.t.findIndex((t) => t >= l.t[0]);
    const keep = cut < 0 ? b.t.length : cut;
    out[id] = { t: [...b.t.slice(0, keep), ...l.t], v: [...b.v.slice(0, keep), ...l.v] };
  }
  return out;
}

// Trailing moving average over a `windowS` second window (0 or 1 = untouched). Keeps timestamps.
export function smooth(series, windowS) {
  if (!series || !windowS || windowS <= 1) return series;
  const { t, v } = series;
  const out = new Array(v.length);
  let lo = 0; let sum = 0; let n = 0;
  for (let i = 0; i < v.length; i += 1) {
    sum += v[i]; n += 1;
    while (t[i] - t[lo] > windowS) { sum -= v[lo]; n -= 1; lo += 1; }
    out[i] = Math.round((sum / n) * 1000) / 1000;
  }
  return { t, v: out };
}

// Cut to the last `spanS` seconds ending at `now`.
export function clip(series, now, spanS) {
  if (!series) return series;
  const from = now - spanS;
  const i = series.t.findIndex((t) => t >= from);
  if (i < 0) return { t: [], v: [] };
  return i === 0 ? series : { t: series.t.slice(i), v: series.v.slice(i) };
}

// uPlot wants one shared x array and one y array per series: union of all timestamps, null where a series
// has no sample (the plot connects across them). `ids` fixes the series order.
export function align(seriesMap, ids) {
  const stamps = new Set();
  for (const id of ids) for (const t of seriesMap[id]?.t || []) stamps.add(t);
  const x = [...stamps].sort((a, b) => a - b);
  const index = new Map(x.map((t, i) => [t, i]));
  const ys = ids.map((id) => {
    const col = new Array(x.length).fill(null);
    const s = seriesMap[id];
    if (s) for (let i = 0; i < s.t.length; i += 1) col[index.get(s.t[i])] = s.v[i];
    return col;
  });
  return { x, ys };
}

// Axis ceiling for the temperature scale: next multiple of 25 above the largest visible value, at least 50.
export function tempCeiling(ys) {
  let max = 0;
  for (const col of ys) for (const v of col) if (v != null && v > max) max = v;
  return Math.max(50, Math.ceil(max / 25) * 25);
}

// "215.3° → 220°" style reading for the legend chips.
export function formatReading(value, target) {
  if (!Number.isFinite(value)) return "—";
  const t = Number.isFinite(target) && target > 0 ? ` → ${Math.round(target)}°` : "";
  return `${value.toFixed(1)}°${t}`;
}

// Points for a tiny SVG sparkline of `values` in a w x h box (padding 1px). Flat data draws a mid line.
export function sparklinePoints(values, w = 80, h = 20) {
  const v = (values || []).filter((x) => Number.isFinite(x));
  if (v.length < 2) return "";
  const lo = Math.min(...v); const hi = Math.max(...v); const span = hi - lo || 1;
  return v.map((y, i) => {
    const px = 1 + (i / (v.length - 1)) * (w - 2);
    const py = hi === lo ? h / 2 : h - 1 - ((y - lo) / span) * (h - 2);
    return `${px.toFixed(1)},${py.toFixed(1)}`;
  }).join(" ");
}

// Display name and unit of one parameter of a Moonraker sensor row (parameter_info is a list of
// {units, ...} in the same order as `values`' keys; fall back to common names).
const UNIT_GUESS = { temperature: "°C", temp: "°C", humidity: "%", pressure: "hPa", gas: "Ω", power: "W", voltage: "V", current: "A" };
export function sensorParameters(sensor) {
  const values = sensor?.values || {};
  const keys = Array.isArray(sensor?.keys) && sensor.keys.length ? sensor.keys.filter((k) => k in values) : Object.keys(values);
  const byField = (key) => (sensor.parameter_info || []).find((p) => p.field === key || p.name === key);
  return keys.map((key, i) => {
    // units: declared for that name, else a guess from the name, else positional (only when the server told us
    // Moonraker's own key order)
    const unit = byField(key)?.units || UNIT_GUESS[key] || (sensor.keys ? sensor.parameter_info?.[i]?.units : "") || "";
    return { key, label: prettify(key), unit, value: values[key], history: sensor.history?.[key] || [] };
  });
}

export function formatSensorValue(value, unit) {
  if (typeof value !== "number" || !Number.isFinite(value)) return value == null ? "—" : String(value);
  const digits = Math.abs(value) >= 100 ? 0 : 1;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

// /thermal_history response -> the chart's series. Moonraker reports heater power and fan speed as 0..1; the
// chart's percent axis wants 0..100. The `.target` and temperature series are kept as they are.
export function historyToSeries(response) {
  const out = {};
  for (const [id, s] of Object.entries(response?.series || {})) {
    if (!s || !Array.isArray(s.t) || !Array.isArray(s.v)) continue;
    const pct = /\.(power|speed)$/.test(id);
    out[id] = { t: s.t, v: pct ? s.v.map((x) => (x == null ? x : x * 100)) : s.v };
  }
  return out;
}

// Hub series that came back in a history response but are not in the current catalogue (e.g. the hub is
// unplugged right now yet recorded the last 6 hours) still get a line.
export function withHistoryDefs(catalog, ids) {
  const have = new Set(catalog.map((d) => d.id));
  const out = [...catalog];
  if (ids.includes(HUB_CHAMBER) && !have.has(HUB_CHAMBER)) out.push({ id: HUB_CHAMBER, label: labelFor(HUB_CHAMBER), group: "sensor", axis: "temp", dashed: false });
  if (ids.includes(HUB_HUMIDITY) && !have.has(HUB_HUMIDITY)) out.push({ id: HUB_HUMIDITY, label: labelFor(HUB_HUMIDITY), group: "humidity", axis: "pct", dashed: false });
  return out;
}
