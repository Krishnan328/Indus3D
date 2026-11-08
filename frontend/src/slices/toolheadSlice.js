// Typed toolhead / thermal actions: one function per control, each posting to
// POST /api/v1/printer/adjust/<control> (see backend/api/routes/adjust.py). The browser sends values and object
// names only; the server validates them and builds the G-code. Sliders call these through
// `useDebouncedCallback` (see ToolheadSlider) so a drag sends one request, not one per pixel.

export function createToolheadSlice(set, get, getApi) {
  let noteTimer = null;

  const note = (ok, message) => {
    const status = { ok, message, ts: Date.now() };
    set({ toolheadStatus: status });
    if (noteTimer) clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { if (get().toolheadStatus === status) set({ toolheadStatus: null }); }, 6000);
  };

  // Returns {ok, status, body, message}; never throws. `okMessage` may be a function of the response body.
  const adjust = async (control, payload = {}, okMessage = "Done") => {
    try {
      const res = await fetch(`${getApi()}/api/v1/printer/adjust/${control}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        const message = body.message || (typeof okMessage === "function" ? okMessage(body) : okMessage);
        note(true, message);
        return { ok: true, status: res.status, body, message };
      }
      const message = res.status === 429 ? "Too many requests: slow down a little"
        : (body.error || body.detail || `HTTP ${res.status}`);
      note(false, message);
      return { ok: false, status: res.status, body, message };
    } catch (e) {
      const message = String(e);
      note(false, message);
      return { ok: false, status: 0, body: {}, message };
    }
  };

  return {
    toolheadStatus: null,   // {ok, message, ts} of the last control action (fades after a few seconds)

    setHeaterTarget: (heater, target) => adjust("heater", { heater, target }, `${heater} target ${target}°C`),
    setFanSpeed: (fan, speed) => adjust("fan", { fan, speed }, `${fan} ${Math.round(speed * 100)}%`),
    setOutputPin: (pin, value) => adjust("output_pin", { pin, value }, `${pin} ${value}`),
    setSpeedFactor: (factor) => adjust("speed", { factor }, `Speed ${factor}%`),
    setFlowFactor: (factor) => adjust("flow", { factor }, `Flow ${factor}%`),
    setPressureAdvance: (advance, smooth_time) =>
      adjust("pressure_advance", smooth_time == null ? { advance } : { advance, smooth_time }, `Pressure advance ${advance}`),
    setRetraction: (values) => adjust("retraction", values, "Retraction updated"),
    babystepZ: (step) => adjust("babystep", { step }, `Z ${step > 0 ? "+" : ""}${step} mm`),
    motorsOff: () => adjust("motors_off", {}, "Motors off"),
    levelAction: (action, extra = {}) => adjust("level", { action, ...extra }, `${action} sent`),
    // Home some axes ("XY", "Z") or all: POST /api/v1/printer/home {axes}
    homeSelected: async (axes = "") => {
      try {
        const res = await fetch(`${getApi()}/api/v1/printer/home`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(axes ? { axes } : {}),
        });
        const body = await res.json().catch(() => ({}));
        const message = res.ok ? `Homing ${axes || "all axes"}` : (body.error || `HTTP ${res.status}`);
        note(res.ok, message);
        return { ok: res.ok, status: res.status, body, message };
      } catch (e) {
        note(false, String(e));
        return { ok: false, status: 0, body: {}, message: String(e) };
      }
    },
    extrude: (amount, feedrate) => adjust("extrude", { amount, ...(feedrate ? { feedrate } : {}) },
      `${amount > 0 ? "Extruded" : "Retracted"} ${Math.abs(amount)} mm`),

    // Saving rewrites printer.cfg after SAVE_CONFIG: always asks first, and says what happens next.
    saveZOffset: async (target) => {
      const where = target === "probe" ? "the probe z_offset" : "the endstop position";
      if (typeof window !== "undefined" && !window.confirm(
        `Save the current Z offset to ${where}? Klipper stages the change and needs SAVE_CONFIG (which restarts the printer) to keep it.`)) {
        return { ok: false, status: 0, body: {}, message: "cancelled" };
      }
      return adjust("save_z_offset", { target, confirmed: true }, "Z offset staged: run SAVE_CONFIG to keep it");
    },
  };
}
