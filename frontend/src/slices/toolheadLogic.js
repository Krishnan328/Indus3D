// Pure helpers for the toolhead / thermals controls (no React, no store): bounds, availability and the
// reasons a control is disabled. Mirrors the limits enforced by backend/api/routes/adjust.py; the server
// is still the authority, these only keep the UI from offering what it would refuse.

export const TEMP_MARGIN_C = 5;
export const FACTOR_RANGE = [10, 300];
export const BABYSTEP_MAX = 0.5;
export const EXTRUDE_MAX_MM = 100;
export const EXTRUDE_FEED_RANGE = [30, 3000];       // mm/min, as /api/v1/control/jog
export const PA_RANGE = [0, 2];

export const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));

export const isPrinting = (state) => state === "printing" || state === "paused";

// Highest setpoint the server will accept for `heater` (configured max_temp minus a margin), or null when unknown.
export function heaterCeiling(limits, heater) {
  const entry = limits?.[String(heater || "").toLowerCase()];
  return entry && Number.isFinite(entry.max_temp) ? Math.max(0, entry.max_temp - TEMP_MARGIN_C) : null;
}

// A temperature typed into a setpoint box -> a number the server accepts, or null when it is not a number.
export function parseSetpoint(text, ceiling) {
  const value = Number.parseFloat(String(text).trim().replace(",", "."));
  if (!Number.isFinite(value)) return null;
  const upper = ceiling == null ? 400 : ceiling;
  return clamp(Math.round(value * 10) / 10, 0, upper);
}

// mm/s (what people type) -> mm/min within the server's bounds.
export function feedrateFromSpeed(mmPerSecond) {
  return clamp(Math.round(Number(mmPerSecond) * 60), EXTRUDE_FEED_RANGE[0], EXTRUDE_FEED_RANGE[1]);
}

// Fan/pin 0..1 <-> percent.
export const toPercent = (fraction) => Math.round(clamp(Number(fraction) || 0, 0, 1) * 100);
export const fromPercent = (percent) => clamp(Number(percent) || 0, 0, 100) / 100;

// Current Z gcode offset (mm) from the gcode_move object, or null.
export function zOffsetOf(status) {
  const origin = status?.gcode_move?.homing_origin;
  return Array.isArray(origin) && Number.isFinite(origin[2]) ? origin[2] : null;
}

// 0.01 -> "+0.01", -0.025 -> "-0.025": increments as shown on babystep buttons.
export function formatStep(step) {
  const text = String(Number(step.toFixed(3)));
  return step > 0 ? `+${text}` : text;
}

// Increments from a user-edited list ("0.01, 0.05"): positive, within the babystep limit, de-duplicated, sorted.
export function cleanIncrements(list, fallback = [0.01, 0.05, 0.1]) {
  const values = (Array.isArray(list) ? list : [])
    .map(Number).filter((v) => Number.isFinite(v) && v > 0 && v <= BABYSTEP_MAX);
  return values.length ? [...new Set(values)].sort((a, b) => a - b) : fallback;
}

export function parseNumberList(text, { min = 0, max = Infinity } = {}) {
  return String(text).split(",").map((v) => Number.parseFloat(v.trim()))
    .filter((v) => Number.isFinite(v) && v > min - 1e-12 && v <= max);
}

// Why a control is unavailable right now (string), or null when it is usable. One place, so the toolhead
// card, the tooltips and the tests agree.
export function reasonDisabled(control, { printing, capabilities = {}, status = {}, connected = true }) {
  if (!connected) return "Klipper status unavailable";
  switch (control) {
    case "motion": case "home": case "motors_off": case "level": case "extrude":
      if (printing) return "Disabled during a print";
      break;
    default:
  }
  if (control === "extrude") {
    const e = status.extruder;
    if (e && e.can_extrude === false) return "Extruder too cold: heat it first";
  }
  if (control === "retraction" && !capabilities.firmware_retraction) return "Klipper has no [firmware_retraction]";
  if (control === "save_probe" && !capabilities.probe) return "No probe configured";
  return null;
}

// Which leveling buttons to show, from capabilities (nothing the printer cannot do is offered).
export function levelingActions(capabilities = {}) {
  const out = [];
  if (capabilities.z_tilt) out.push({ action: "Z_TILT_ADJUST", label: "Z tilt adjust" });
  if (capabilities.quad_gantry_level) out.push({ action: "QUAD_GANTRY_LEVEL", label: "Quad gantry level" });
  if (capabilities.screws_tilt_adjust) out.push({ action: "SCREWS_TILT_CALCULATE", label: "Screws tilt calculate" });
  if (capabilities.bed_screws) out.push({ action: "BED_SCREWS_ADJUST", label: "Bed screws adjust" });
  if (capabilities.probe) out.push({ action: "PROBE_CALIBRATE", label: "Probe calibrate" });
  return out;
}

// Tool-card macro buttons (load / unload / clean / park) from capabilities.tool_macros.
const TOOL_MACRO_LABELS = [["load_filament", "Load"], ["unload_filament", "Unload"],
  ["clean_nozzle", "Clean nozzle"], ["park_toolhead", "Park"]];
export function toolMacroButtons(capabilities = {}) {
  const macros = capabilities.tool_macros || {};
  return TOOL_MACRO_LABELS.filter(([key]) => macros[key]).map(([key, label]) => ({ key, label, macro: macros[key] }));
}

// Single-extruder UI for now: the first extruder heater. Multi-extruder / extruder_stepper are deferred.
export function primaryExtruder(capabilities = {}) {
  const list = capabilities.extruders || [];
  return list.includes("extruder") ? "extruder" : (list[0] || "extruder");
}

// Controllable fans: the part fan and fan_generic. heater_fan / controller_fan are Klipper-managed.
export function controllableFans(capabilities = {}) {
  return (capabilities.fans || []).filter((f) => f === "fan" || f.startsWith("fan_generic "));
}

export const shortName = (object) => String(object).replace(/^(heater_generic|fan_generic|output_pin|temperature_sensor|temperature_fan|heater_fan|controller_fan) /, "");

// Annular sector between radii r0..r1 centred on `mid` degrees (0 = up, clockwise), 90 degrees wide.
export function sectorPath(cx, cy, r0, r1, mid) {
  const pt = (r, deg) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const [a0, a1] = [mid - 44, mid + 44];                 // 2 degrees of gap between the four directions
  const [x0, y0] = pt(r1, a0); const [x1, y1] = pt(r1, a1);
  const [x2, y2] = pt(r0, a1); const [x3, y3] = pt(r0, a0);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r1} ${r1} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)} L${x2.toFixed(2)} ${y2.toFixed(2)} A${r0} ${r0} 0 0 0 ${x3.toFixed(2)} ${y3.toFixed(2)}Z`;
}

