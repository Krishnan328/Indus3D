import { create } from "zustand";

// Keep this build's API port in sync with backend/.env's FLASK_PORT. Vite
// substitutes VITE_* values at build time, so restart the dev server or
// rebuild after changing frontend/.env.
// In production (served by Flask or Nginx), connect to the page's own origin
// and port. In local Vite dev mode, connect to the backend on FLASK_PORT (default 5001).
const isDev    = import.meta.env.DEV;
const HOST     = window.location.hostname;
const PROTO    = window.location.protocol === "https:" ? "https:" : "http:";
const WS_PROTO = window.location.protocol === "https:" ? "wss:" : "ws:";
let API_PORT   = isDev
  ? (import.meta.env.VITE_API_PORT || "5001")
  : (window.location.port || (window.location.protocol === "https:" ? "443" : "80"));
let API        = isDev ? `http://${HOST}:${API_PORT}` : window.location.origin;
let WS_URL     = isDev ? `ws://${HOST}:${API_PORT}/api/v1/ws/twin` : `${WS_PROTO}//${window.location.host}/api/v1/ws/twin`;

let isHunting = false;
const huntForApiPort = async () => {
  if (isHunting) return false;
  isHunting = true;
  const basePort = parseInt(import.meta.env.VITE_API_PORT || "5001", 10);
  
  for (let p = basePort; p < basePort + 10; p++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 800);
      const res = await fetch(`http://${HOST}:${p}/api/v1/health`, { signal: controller.signal });
      clearTimeout(timeoutId);
      
      if (res.ok) {
        if (p.toString() !== API_PORT) {
          console.log(`[Indus3D] Port switched! Found active backend on port ${p}`);
          API_PORT = p.toString();
          API = `http://${HOST}:${API_PORT}`;
          WS_URL = `ws://${HOST}:${API_PORT}/api/v1/ws/twin`;
        }
        isHunting = false;
        return true;
      }
    } catch {
      // Port inactive or timeout
    }
  }
  isHunting = false;
  return false;
};
let THRESHOLDS = {
  lag_magnitude_mm:  0.8,
  stress_score_axis: 0.5,
  ext_heat_cycles:   500,
  bed_heat_cycles:   500,
};

// ── Alert derivation ──────────────────────────────────────────────────────────
// CRITICAL: alerts only fire when print_state === "printing"
// This prevents false positives during homing, heating, and standby.
function deriveAlerts(data) {
  const alerts = [];
  const kin   = data.kinematics  || {};
  const thm   = data.thermals    || {};
  const ext   = data.extrusion   || {};
  const state = data.print_state || "standby";

  const isPrinting = state === "printing";

  // ── Thermal runaway — always alert (safety critical) ─────────────────────
  if (thm.ext_runaway_flag)
    alerts.push({ id: "ext_runaway", level: "critical",
      msg: "Extruder thermal runaway detected" });
  if (thm.bed_runaway_flag)
    alerts.push({ id: "bed_runaway", level: "critical",
      msg: "Bed thermal runaway detected" });

  // ── Bed hardware & screw collision hazard — always alert ──────────────────
  if (data.bed_collision_hazard) {
    alerts.push({
      id: "bed_collision",
      level: "critical",
      msg: `Bed collision hazard: toolhead near bed screw / clip #${(data.bed_collision_zone ?? 0) + 1}!`
    });
  }

  // ── Disk space — always alert (system health) ───────────────────────────
  const disk = data.disk || {};
  if (disk.critical)
    alerts.push({ id: "disk_critical", level: "critical",
      msg: `Disk space critically low (${disk.free_gb} GB free)` });
  else if (disk.warn)
    alerts.push({ id: "disk_warn", level: "warn",
      msg: `Disk space low (${disk.free_gb} GB free)` });

  // ── Below this point: only during active printing ────────────────────────
  if (!isPrinting) return alerts;

  if ((kin.lag_magnitude_mm ?? 0) > THRESHOLDS.lag_magnitude_mm)
    alerts.push({ id: "lag", level: "warn",
      msg: `Position lag ${kin.lag_magnitude_mm?.toFixed(2)} mm` });

  if (ext.under_extrusion_flag)
    alerts.push({ id: "under_ext", level: "warn",
      msg: "E-axis flow mismatch (possible under-extrusion)" });

  if (ext.over_extrusion_flag)
    alerts.push({ id: "over_ext", level: "warn",
      msg: "E-axis flow mismatch (possible over-extrusion)" });

  const stress = kin.stress_score || {};
  for (const axis of ["X", "Y", "Z"]) {
    if ((stress[axis] ?? 0) > THRESHOLDS.stress_score_axis)
      alerts.push({ id: `stress_${axis}`, level: "warn",
        msg: `${axis}-axis belt stress high (${stress[axis]?.toFixed(3)})` });
  }

  if ((thm.ext_heat_cycles ?? 0) > THRESHOLDS.ext_heat_cycles)
    alerts.push({ id: "ext_cycles", level: "info",
      msg: `Extruder heat cycles: ${thm.ext_heat_cycles} — inspect heater` });
  if ((thm.bed_heat_cycles ?? 0) > THRESHOLDS.bed_heat_cycles)
    alerts.push({ id: "bed_cycles", level: "info",
      msg: `Bed heat cycles: ${thm.bed_heat_cycles} — inspect wiring` });

  // ── Vibration alerts from DSP pipeline ───────────────────────────────────
  if (isPrinting) {
    const vib = data.vibration || {};
    for (const a of (vib.alerts || [])) {
      alerts.push({ id: a.id, level: a.level, msg: a.msg });
    }
  }

  return alerts;
}

export const useStore = create((set, get) => ({

  // ── Authentication ────────────────────────────────────────────────────────
  // Mirrors the backend's auth_required / authenticated state. Fetched once
  // on mount by App.jsx — when auth is disabled, the login screen never
  // appears and the rest of the app works exactly as before.
  authStatus: { auth_required: false, authenticated: true, loading: true },

  fetchAuthStatus: async () => {
    try {
      const res  = await fetch(`${API}/api/v1/auth/status`);
      const data = await res.json();
      set({ authStatus: { ...data, loading: false } });
    } catch {
      set({ authStatus: { auth_required: false, authenticated: true, loading: false } });
    }
  },

  login: async (password) => {
    const res = await fetch(`${API}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (res.ok) await get().fetchAuthStatus();
    return { ok: res.ok, ...data };
  },

  logout: async () => {
    await fetch(`${API}/api/v1/auth/logout`, { method: "POST" });
    await get().fetchAuthStatus();
  },

  // ── UI theme & profile sync ──────────────────────────────────────────
  theme: localStorage.getItem("indus3d_theme") || "classic",
  dashboardMode: localStorage.getItem("indus3d_mode") || "dynamic",
  isDarkMode: localStorage.getItem("indus3d_dark") !== "false",
  uiPrefs: (() => {
    try {
      return JSON.parse(localStorage.getItem("indus3d_ui_prefs") || "{}");
    } catch {
      return {};
    }
  })(),

  fetchPreferences: async () => {
    try {
      const res = await fetch(`${API}/api/v1/profile/preferences`);
      if (res.ok) {
        const prefs = await res.json();
        if (prefs.theme) {
          localStorage.setItem("indus3d_theme", prefs.theme);
          set({ theme: prefs.theme });
        }
        if (prefs.dashboardMode) {
          localStorage.setItem("indus3d_mode", prefs.dashboardMode);
          set({ dashboardMode: prefs.dashboardMode });
        }
        if (prefs.isDarkMode) {
          localStorage.setItem("indus3d_dark", prefs.isDarkMode);
          set({ isDarkMode: prefs.isDarkMode === "true" });
        }
      }
    } catch { /* silent fallback to localstorage */ }
  },

  syncPreference: async (key, value) => {
    try {
      await fetch(`${API}/api/v1/profile/preferences`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: value })
      });
    } catch { /* silent */ }
  },

  setDashboardMode: (mode) => {
    localStorage.setItem("indus3d_mode", mode);
    set({ dashboardMode: mode });
    get().syncPreference("dashboardMode", mode);
  },
  setTheme: (theme) => {
    localStorage.setItem("indus3d_theme", theme);
    set({ theme });
    get().syncPreference("theme", theme);
  },
  setIsDarkMode: (isDarkMode) => {
    localStorage.setItem("indus3d_dark", String(isDarkMode));
    set({ isDarkMode });
    get().syncPreference("isDarkMode", String(isDarkMode));
  },

  // ── Remote config (loaded once from /api/config) ──────────────────────────
  remoteConfig: {
    moonraker_url:     "",
    webcam_stream_url: "",
  },

  fetchRemoteConfig: async () => {
    try {
      const res  = await fetch(`${API}/api/v1/config`);
      const data = await res.json();
      set({ remoteConfig: data });
    } catch { /* use defaults */ }
  },

  // ── Printer profile ───────────────────────────────────────────────────────
  profile:       null,
  profileSource: "",
  bed: {
    size_x_mm: 300,
    size_y_mm: 300,
    size_z_mm: 400,
    origin_center: false,
    min_x: 0,
    max_x: 300,
    min_y: 0,
    max_y: 300,
    printable_area: [[0, 0], [300, 0], [300, 300], [0, 300]],
    bed_exclude_area: [],
    clearance_height_mm: 10,
    has_custom_model: false,
    custom_model_filename: null,
    source_name: "default",
  },
  simMode: false,

  fetchProfile: async () => {
    try {
      const res  = await fetch(`${API}/api/v1/profile/`);
      const data = await res.json();
      const a    = data.alerts ?? {};
      THRESHOLDS = {
        lag_magnitude_mm:  a.lag_magnitude_warn_mm  ?? 0.8,
        stress_score_axis: a.stress_score_warn       ?? 0.5,
        ext_heat_cycles:   a.ext_heat_cycles_warn    ?? 500,
        bed_heat_cycles:   a.bed_heat_cycles_warn    ?? 500,
      };
      set({ profile: data, profileSource: data._source ?? "unknown",
            bed: data.bed ?? get().bed });
    } catch {
      const found = await huntForApiPort();
      if (found) {
        try {
          const res  = await fetch(`${API}/api/v1/profile/`);
          const data = await res.json();
          set({ profile: data, profileSource: data._source ?? "unknown", bed: data.bed ?? get().bed });
        } catch {
          // Profile reload will be retried on the next polling cycle.
        }
      }
    }
  },

  reloadProfile: async () => {
    try {
      const res  = await fetch(`${API}/api/v1/profile/reload`, { method: "POST" });
      const data = await res.json();
      if (data.status === "ok") { await get().fetchProfile(); return { ok: true }; }
      return { ok: false, message: data.message };
    } catch (e) { return { ok: false, message: e.toString() }; }
  },

  // ── Core telemetry ────────────────────────────────────────────────────────
  telemetry: {
    x: 0, y: 0, z: 0, extTemp: 0, bedTemp: 0,
    extTarget: 0, bedTarget: 0,
    state: "standby", filename: "", file_position: 0, fault: false,
    progress: 0, print_duration: 0, time_remaining: 0,
    speed_factor: 100, flow_factor: 100,
  },

  kinematics: {
    odometry_m: { X: 0, Y: 0, Z: 0, E: 0 },
    lag_x_mm: 0, lag_y_mm: 0, lag_z_mm: 0, lag_magnitude_mm: 0,
    derived_velocity_mm_s: 0, accel_mm_s2: 0,
    reversal_counts: { X: 0, Y: 0, Z: 0 }, stress_score: { X: 0, Y: 0, Z: 0 },
  },
  thermals: {
    ext_error_c: 0, ext_pid_shadow: 0, ext_pid_actual: 0, ext_pid_delta: 0,
    ext_at_target: false, ext_runaway_flag: false, ext_heat_cycles: 0, ext_max_temp: 300,
    bed_error_c: 0, bed_at_target: false,
    bed_runaway_flag: false, bed_heat_cycles: 0, bed_max_temp: 120,
  },
  extrusion: {
    feed_rate_mm_s: 0, volumetric_flow_mm3_s: 0, avg_flow_mm3_s: 0,
    expected_flow_mm3_s: 0, flow_ratio: 1, under_extrusion_flag: false,
    over_extrusion_flag: false, pressure_estimate_mm: 0,
    filament_consumed_m: 0, max_volumetric_flow: 12,
    nozzle_dia_mm: 0.4, filament_dia_mm: 1.75, layer_height_mm: 0.2,
  },

  // ── Vibration / DSP pipeline ──────────────────────────────────────────────
  vibration: null,  // null = DSP not available; object = {x, y, z, alerts, available}

  // ── Quality control ───────────────────────────────────────────────────────
  quality: {
    active: {
      flow_pct: 100, speed_pct: 100, shaper_hz: 0, enabled: false,
      pa: 0.04, temp: 220, fan: 0, z_offset: 0.0, accel: 3000,
      velocity: 300, scv: 5.0, retraction: 1.0, pressure: 0.0,
    },
    corrections: [],
  },

  // ── G-code lines (parsed from file for terminal + visualiser) ─────────────
  gcodeLines: [],

  // ── Live commands (quality controller + user) for terminal ────────────────
  // These come from the WS payload in live mode, or gcode_feed in sim mode
  liveCommands: [],

  // ── Sensors ───────────────────────────────────────────────────────────────
  power:            { voltage: 0, current: 0, power: 0 },
  environment:      { temperature: 0, humidity: 0 },
  disk:             { total_gb: null, used_gb: null, free_gb: null, usage_pct: null, warn: false, critical: false },
  // One point per second, populated from the 10 Hz WebSocket feed. Keeping
  // this client-side avoids another high-frequency HTTP endpoint just for a
  // dashboard chart.
  temperatureHistory: [],
  printHistory:     [],
  maintenanceHints: [],
  maintenanceStatus: [],
  maintenanceConfig: {},

  updateMaintenanceConfig: async (cfg) => {
    try {
      await fetch(`${API}/api/v1/maintenance/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg)
      });
      useStore.getState().fetchSensorData();
    } catch { /* silent */ }
  },

  fetchSensorData: async () => {
    try {
      const [pr, er, hr, mr] = await Promise.all([
        fetch(`${API}/api/v1/power`),
        fetch(`${API}/api/v1/environment`),
        fetch(`${API}/api/v1/history`),
        fetch(`${API}/api/v1/maintenance`),
      ]);
      
      // Macros
      try {
        const res = await fetch(`${API}/api/v1/printer/macros`);
        if (res.ok) {
          const data = await res.json();
          set({ macros: data.macros || [] });
        }
      } catch {
        // Macros are optional; retain the last known list on a transient error.
      }

      // Lifetime Stats
      try {
        const res = await fetch(`${API}/api/v1/twin/stats/lifetime`);
        if (res.ok) {
          set({ lifetimeStats: await res.json() });
        }
      } catch (err) {
        console.warn("Failed to fetch lifetime stats", err);
      }

      await Promise.all([
      ]);
      if (pr.ok) set({ power:            await pr.json() });
      if (er.ok) set({ environment:      await er.json() });
      if (hr.ok) set({ printHistory:     await hr.json() });
      if (mr.ok) { 
        const d = await mr.json(); 
        set({ 
          maintenanceHints: d.hints ?? [], 
          maintenanceStatus: d.status ?? [],
          maintenanceConfig: d.config ?? {}
        }); 
      }
    } catch { /* silent */ }
  },

  // ── Alerts + action log ───────────────────────────────────────────────────
  alerts:       [],
  dismissedIds: new Set(),
  actionLog:    [],

  dismissAlert:   (id) => set((s) => ({ dismissedIds: new Set([...s.dismissedIds, id]) })),
  clearDismissed: ()   => set({ dismissedIds: new Set() }),

  excludeObject: async (name) => {
    try {
      const res = await fetch(`${API}/api/v1/twin/exclude_object`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
      });
      if (!res.ok) alert("Failed to exclude: " + await res.text());
    } catch (e) { alert("Failed to exclude: " + e.message); }
  },

  executeAlertAction: async (alertId) => {
    try {
      const res  = await fetch(`${API}/api/v1/twin/action/execute`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ alert_id: alertId }),
      });
      const data = await res.json();
      if (data.status === "executed") {
        set((s) => ({
          actionLog: [{ ts: Date.now(), ...data }, ...s.actionLog].slice(0, 100),
        }));
      }
      return data;
    } catch (e) { return { status: "error", message: e.toString() }; }
  },

  fetchActionLog: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/action/log?limit=50`);
      const data = await res.json(); set({ actionLog: Array.isArray(data) ? data : [] });
    } catch { /* silent */ }
  },

  // ── Spoolman (filament inventory, via Moonraker's [spoolman] component) ────
  spoolmanConnected: false,
  spools: [],
  activeSpoolId: null,
  spoolmanError: null,

  fetchSpoolStatus: async () => {
    try {
      const res  = await fetch(`${API}/api/v1/printer/spoolman/status`);
      if (!res.ok) { set({ spoolmanConnected: false, spoolmanError: "not configured" }); return; }
      const data = await res.json();
      set({
        spoolmanConnected: !!data.spoolman_connected,
        activeSpoolId: data.spool_id ?? null,
        spoolmanError: null,
      });
    } catch {
      set({ spoolmanConnected: false, spoolmanError: "unreachable" });
    }
  },

  fetchSpools: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/spoolman/spools`);
      if (!res.ok) return;
      const data = await res.json();
      set({ spools: Array.isArray(data) ? data : [] });
    } catch { /* silent — spoolmanConnected already reflects reachability */ }
  },

  setActiveSpool: async (spoolId) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/spoolman/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spool_id: spoolId }),
      });
      const data = await res.json();
      set({ activeSpoolId: data.spool_id ?? null });
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── Power devices (relays/smart plugs, via Moonraker's [power] component) ──
  powerDevices: [],
  powerCutoffConfig: { enabled: false, device: null },

  fetchPowerDevices: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/power/devices`);
      if (!res.ok) { set({ powerDevices: [] }); return; }
      const data = await res.json();
      set({ powerDevices: data.devices ?? [] });
    } catch { set({ powerDevices: [] }); }
  },

  fetchPowerCutoffConfig: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/power/cutoff_config`);
      if (!res.ok) return;
      set({ powerCutoffConfig: await res.json() });
    } catch { /* silent — shown as "unknown" */ }
  },

  setPowerDevice: async (device, action) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/power/${device}/${action}`, { method: "POST" });
      const data = await res.json();
      get().fetchPowerDevices();
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── Host / firmware safety actions ───────────────────────────────────────
  // Keep the action mapping in one place so every UI surface uses the same
  // backend proxy. In particular, the browser must never contact Moonraker
  // directly for an emergency stop or a host-level action.
  powerAction: async (action) => {
    const routes = {
      emergency_stop: "emergency_stop",
      restart: "restart",
      firmware_restart: "firmware_restart",
      reboot: "machine/reboot",
      shutdown: "machine/shutdown",
    };
    const route = routes[action];
    if (!route) return { error: `Unknown power action: ${action}` };

    try {
      const res = await fetch(`${API}/api/v1/printer/${route}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      return data;
    } catch (error) {
      return { error: error.message || String(error) };
    }
  },

  // ── Timelapse ────────────────────────────────────────────────────────────
  timelapses: [],
  timelapseStatus: { active: false, frame_count: 0 },

  fetchTimelapses: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/timelapse/list`);
      if (!res.ok) return;
      set({ timelapses: await res.json() });
    } catch { /* silent */ }
  },

  fetchTimelapseStatus: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/timelapse/status`);
      if (!res.ok) return;
      set({ timelapseStatus: await res.json() });
    } catch { /* silent */ }
  },

  timelapseConfig: { enabled: false, mode: "interval", interval_s: 10, fps: 15 },
  timelapseConfigLoaded: false,

  fetchTimelapseConfig: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/timelapse/config`);
      if (!res.ok) return;
      set({ timelapseConfig: await res.json(), timelapseConfigLoaded: true });
    } catch { /* silent — settings tab shows defaults */ }
  },

  saveTimelapseConfig: async (partial) => {
    // Backend keys are prefixed (timelapse_enabled, timelapse_mode, ...);
    // the frontend works with the unprefixed shape returned by GET, so
    // translate here rather than leaking the cfg-file naming into the UI.
    const body = {};
    if ("enabled" in partial)    body.timelapse_enabled = partial.enabled;
    if ("mode" in partial)       body.timelapse_mode = partial.mode;
    if ("interval_s" in partial) body.timelapse_interval_s = partial.interval_s;
    if ("fps" in partial)        body.timelapse_fps = partial.fps;
    try {
      const res = await fetch(`${API}/api/v1/twin/timelapse/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set({ timelapseConfig: data });
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── Multi-printer (switch-based — one active connection at a time) ────────
  printerInstances: { active: "local", printers: [] },

  fetchPrinterInstances: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/instances`);
      if (!res.ok) return;
      set({ printerInstances: await res.json() });
    } catch { /* silent — settings tab shows last-known list */ }
  },

  addPrinterInstance: async (name, host, port) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/instances`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, host, port }),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set({ printerInstances: data });
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  removePrinterInstance: async (id) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/instances/${encodeURIComponent(id)}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set({ printerInstances: data });
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  activatePrinterInstance: async (id) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/instances/${encodeURIComponent(id)}/activate`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set({ printerInstances: data });
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── LEDs (see backend services/led_controller.py, config/led_profiles.py) ──
  leds: [],
  ledProfile: { enabled: false, led_name: null, colors: {} },

  fetchLeds: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/leds`);
      if (!res.ok) return;
      const data = await res.json();
      set({ leds: data.leds || [] });
    } catch { /* silent — settings tab shows empty list */ }
  },

  fetchLedProfile: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/led_profile`);
      if (!res.ok) return;
      set({ ledProfile: await res.json() });
    } catch { /* silent */ }
  },

  saveLedProfile: async (profile) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/led_profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set({ ledProfile: data });
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  setLedColorLive: async (ledName, hexColor) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/leds/set`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ led_name: ledName, color: hexColor }),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  applyLedProfileState: async (state) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/led_profile/apply_state`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state }),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      return { ok: true, color: data.color };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  turnLedsOff: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/leds/off`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── Vision Inspector (edge/ companion device — see api/routes/edge.py) ────
  edgeStatus: { connected: false, last_heartbeat: null, last_detection: null, config: { enabled: false, threshold_pct: 70, cooldown_s: 120 } },

  fetchEdgeStatus: async () => {
    try {
      const res = await fetch(`${API}/api/v1/edge/status`);
      if (!res.ok) return;
      set({ edgeStatus: await res.json() });
    } catch { /* silent — companion device may simply not be set up */ }
  },

  saveEdgeConfig: async (partial) => {
    const body = {};
    if ("enabled" in partial)     body.edge_inspection_enabled = partial.enabled;
    if ("threshold_pct" in partial) body.edge_inspection_threshold_pct = partial.threshold_pct;
    if ("cooldown_s" in partial)  body.edge_inspection_cooldown_s = partial.cooldown_s;
    try {
      const res = await fetch(`${API}/api/v1/edge/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return { error: data.error || `HTTP ${res.status}` };
      set((state) => ({ edgeStatus: { ...state.edgeStatus, config: { ...state.edgeStatus.config, ...data } } }));
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  exportSettingsBackup: () => {
    const state = get();
    return {
      _indus3d_settings_backup: true,
      version: 1,
      exportedAt: new Date().toISOString(),
      theme: state.theme,
      dashboardMode: state.dashboardMode,
      isDarkMode: state.isDarkMode,
      uiPrefs: state.uiPrefs,
      presets: state.presets,
      cooldownGcode: state.cooldownGcode,
    };
  },

  importSettingsBackup: (data) => {
    if (!data || typeof data !== "object" || !data._indus3d_settings_backup) {
      return { error: "This doesn't look like an Indus3D settings backup file." };
    }
    try {
      if (data.uiPrefs && typeof data.uiPrefs === "object") {
        const merged = { ...get().uiPrefs, ...data.uiPrefs };
        localStorage.setItem("indus3d_ui_prefs", JSON.stringify(merged));
        set({ uiPrefs: merged });
      }
      if (Array.isArray(data.presets)) {
        localStorage.setItem("indus3d_presets", JSON.stringify(data.presets));
        set({ presets: data.presets });
      }
      if (typeof data.cooldownGcode === "string") {
        localStorage.setItem("indus3d_cooldown_gcode", data.cooldownGcode);
        set({ cooldownGcode: data.cooldownGcode });
      }
      if (typeof data.theme === "string") {
        localStorage.setItem("indus3d_theme", data.theme);
        set({ theme: data.theme });
      }
      if (typeof data.dashboardMode === "string") {
        localStorage.setItem("indus3d_mode", data.dashboardMode);
        set({ dashboardMode: data.dashboardMode });
      }
      if (typeof data.isDarkMode === "boolean") {
        localStorage.setItem("indus3d_dark", String(data.isDarkMode));
        set({ isDarkMode: data.isDarkMode });
      }
      return { ok: true };
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── File manager ─────────────────────────────────────────────────────────
  gcodeFiles: [],
  gcodeMetadata: {},   // { [path]: metadata object | 'loading' | 'error' }

  fetchGcodeFiles: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/files/list`);
      if (!res.ok) return;
      const data = await res.json();
      set({ gcodeFiles: Array.isArray(data) ? data : [] });
    } catch { set({ gcodeFiles: [] }); }
  },

  fetchGcodeMetadata: async (path) => {
    if (get().gcodeMetadata[path]) return;  // already fetched or in flight
    set((s) => ({ gcodeMetadata: { ...s.gcodeMetadata, [path]: "loading" } }));
    try {
      const res = await fetch(`${API}/api/v1/printer/files/metadata?filename=${encodeURIComponent(path)}`);
      const data = res.ok ? await res.json() : "error";
      set((s) => ({ gcodeMetadata: { ...s.gcodeMetadata, [path]: data } }));
    } catch {
      set((s) => ({ gcodeMetadata: { ...s.gcodeMetadata, [path]: "error" } }));
    }
  },

  deleteGcodeFile: async (path) => {
    try {
      const res = await fetch(`${API}/api/v1/printer/files/gcodes/${encodeURIComponent(path)}`, { method: "DELETE" });
      if (res.ok) get().fetchGcodeFiles();
      return res.ok;
    } catch { return false; }
  },

  startPrintFile: async (path) => {
    try {
      const res = await fetch(`${API}/api/v1/print/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: path }),
      });
      return res.json();
    } catch (e) {
      return { error: e.toString() };
    }
  },

  // ── Input-shaper tuner ───────────────────────────────────────────────────
  shaperCurrent: { freq: 0, bed_mass_g: 0, shaper_type: "mzv" },
  shaperJob: { status: "idle", axis: null, result: null, error: null },

  fetchShaperCurrent: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/shaper/current`);
      if (res.ok) set({ shaperCurrent: await res.json() });
    } catch { /* Backend may be offline while developing the UI. */ }
  },

  fetchShaperStatus: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/shaper/status`);
      if (res.ok) set({ shaperJob: await res.json() });
    } catch { /* silent */ }
  },

  startShaperCalibration: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/shaper/calibrate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ axis: "y", confirmed: true }),
      });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  applyShaperResult: async (shaperType, freq) => {
    try {
      const res = await fetch(`${API}/api/v1/twin/shaper/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shaper_type: shaperType, freq, confirmed: true }),
      });
      const data = await res.json();
      if (data.applied) get().fetchShaperCurrent();
      return data;
    } catch (e) { return { error: e.toString() }; }
  },

  setShaperBedMass: async (grams) => {
    try {
      const res = await fetch(`${API}/api/v1/twin/shaper/bed_mass`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grams }),
      });
      const data = await res.json();
      if (data.applied) get().fetchShaperCurrent();
      return data;
    } catch (e) { return { error: e.toString() }; }
  },

  // ── Notifications (read-only status — credentials live in .env) ────────────
  notificationStatus: { configured: false, channels: { discord: false, telegram: false }, notify_on_warn: false },

  fetchNotificationStatus: async () => {
    try {
      const res = await fetch(`${API}/api/v1/twin/notifications/status`);
      if (!res.ok) return;
      set({ notificationStatus: await res.json() });
    } catch { /* silent — shown as not configured */ }
  },

  // ── Print controls ────────────────────────────────────────────────────────
  uploadAndPrint: async (file, startNow = false) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const res = await fetch(
      `${API}/api/v1/print/upload${startNow ? "?start=1" : ""}`,
      { method: "POST", body: fd }
    );
    return res.json();
  },

  pausePrint:  async () => { await fetch(`${API}/api/v1/print/pause`,  { method: "POST" }); },
  resumePrint: async () => { await fetch(`${API}/api/v1/print/resume`, { method: "POST" }); },
  cancelPrint: async () => { await fetch(`${API}/api/v1/print/cancel`, { method: "POST" }); },

  toggleAutopilot: async (enabled) => {
    try {
      const res = await fetch(`${API}/api/v1/twin/auto-pilot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled })
      });
      if (res.ok) {
        const data = await res.json();
        // Use confirmed server value (not just the requested value)
        const confirmed = data.auto_pilot_enabled ?? enabled;
        set((s) => ({
          quality: {
            ...s.quality,
            active: { ...s.quality.active, enabled: confirmed },
          },
        }));
      }
    } catch (e) { console.error("Autopilot toggle failed:", e); }
  },

  // ── Bed geometry & collision safety actions ────────────────────────────────
  fetchBedConfig: async () => {
    try {
      const res = await fetch(`${API}/api/v1/bed/config`);
      const data = await res.json();
      if (data && !data.error) {
        set({ bed: { ...get().bed, ...data } });
      }
      return data;
    } catch (e) {
      console.error("fetchBedConfig failed:", e);
    }
  },

  importOrcaBed: async (fileOrJson) => {
    try {
      let res;
      if (fileOrJson instanceof File) {
        const fd = new FormData();
        fd.append("file", fileOrJson);
        res = await fetch(`${API}/api/v1/bed/import-orca`, { method: "POST", body: fd });
      } else {
        res = await fetch(`${API}/api/v1/bed/import-orca`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fileOrJson)
        });
      }
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  uploadBedStl: async (file) => {
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API}/api/v1/bed/upload-stl`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  deleteBedStl: async () => {
    try {
      const res = await fetch(`${API}/api/v1/bed/model`, { method: "DELETE" });
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  addCornerScrewsPreset: async (insetX = 30, insetY = 30, radius = 12) => {
    try {
      const res = await fetch(`${API}/api/v1/bed/add-corner-screws`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inset_x: insetX, inset_y: insetY, radius })
      });
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  clearBedExclusions: async () => {
    try {
      const res = await fetch(`${API}/api/v1/bed/clear-exclusions`, { method: "POST" });
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  updateBedConfig: async (cfg) => {
    try {
      const res = await fetch(`${API}/api/v1/bed/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg)
      });
      const data = await res.json();
      if (data.status === "ok") {
        await get().fetchProfile();
        await get().fetchBedConfig();
      }
      return data;
    } catch (e) {
      return { error: e.toString() };
    }
  },

  sendGcode: async (cmd) => {
    try {
      const res = await fetch(`${API}/api/v1/control/execute`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ command: cmd }),
      });
      return res.json();
    } catch { return { status: "error" }; }
  },

  homeAxes: async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/home`, { method: "POST" });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  jogToolhead: async (delta, feedrate = 3000) => {
    try {
      const res = await fetch(`${API}/api/v1/control/jog`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...delta, feedrate }),
      });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  calibrationStatus: { ready: false, simulated: false, print_state: "offline", defaults: {} },
  fetchCalibrationStatus: async () => {
    try {
      const res = await fetch(`${API}/api/v1/calibration/status`);
      if (res.ok) set({ calibrationStatus: await res.json() });
    } catch { /* modal reports an unavailable backend */ }
  },

  runCalibrationStep: async (step, options = {}) => {
    try {
      const res = await fetch(`${API}/api/v1/calibration/run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step, confirmed: true, ...options }),
      });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  exportAnnotatedGcode: async () => {
    try {
      const url = `${API}/api/v1/export/annotated-gcode`;
      window.open(url, '_blank');
    } catch { /* silent */ }
  },

  uploadPATest: async (options = {}) => {
    try {
      const res = await fetch(`${API}/api/v1/calibration/pa-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(options),
      });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  uploadFlowSample: async () => {
    try {
      const res = await fetch(`${API}/api/v1/calibration/flow-sample`, { method: "POST" });
      return await res.json();
    } catch (e) { return { error: e.toString() }; }
  },

  // ── Replay ────────────────────────────────────────────────────────────────
  replaySnapshots:  [],
  replayCursor:     0,
  replayPlaying:    false,
  replayIntervalId: null,

  fetchReplaySnapshots: async (limit = 500) => {
    try {
      const res = await fetch(`${API}/api/v1/twin/snapshots?limit=${limit}`);
      set({ replaySnapshots: await res.json(), replayCursor: 0, replayPlaying: false });
    } catch { /* replay data is optional */ }
  },

  setReplayCursor: (idx) => set({ replayCursor: idx }),

  startReplay: () => {
    const { replaySnapshots, replayCursor, replayIntervalId } = get();
    if (!replaySnapshots.length) return;
    if (replayIntervalId) clearInterval(replayIntervalId);
    let cursor = replayCursor;
    const id = setInterval(() => {
      cursor++;
      if (cursor >= replaySnapshots.length) {
        clearInterval(id); set({ replayPlaying: false, replayIntervalId: null }); return;
      }
      const snap = replaySnapshots[cursor];
      set({
        replayCursor: cursor,
        telemetry: {
          x: snap.cmd_x, y: snap.cmd_y, z: snap.cmd_z,
          extTemp: snap.ext_temp, bedTemp: snap.bed_temp,
          state: snap.print_state, filename: snap.filename,
          file_position: 0, fault: false,
          progress: 0, print_duration: 0, time_remaining: 0,
          speed_factor: 100, flow_factor: 100,
        },
      });
    }, 100);
    set({ replayPlaying: true, replayIntervalId: id });
  },

  stopReplay: () => {
    const { replayIntervalId } = get();
    if (replayIntervalId) clearInterval(replayIntervalId);
    set({ replayPlaying: false, replayIntervalId: null });
  },

  // ── WebSocket ─────────────────────────────────────────────────────────────
  wsRef: null,

  initWebSocket: () => {
    let reconnectTimer = null;
    const connect = () => {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      };

      ws.onmessage = (event) => {
        try {
          const d = JSON.parse(event.data);
          const { dismissedIds } = get();

          const rawAlerts = deriveAlerts(d);
          const alerts    = rawAlerts
            .filter((a) => !dismissedIds.has(a.id))
            .map((a)    => ({ ...a, ts: Date.now() }));

          // Auto-execute critical alerts only (safety — no user confirmation needed)
          rawAlerts
            .filter((a) => a.level === "critical" && !dismissedIds.has(a.id))
            .forEach((a) => get().executeAlertAction(a.id));

          // simMode: latch once true
          const newSimMode = d.sim === true || get().simMode;

          // Terminal feed:
          // Sim: use gcode_feed directly
          // Live: use live_commands (quality controller + user commands)
          let liveCommands = get().liveCommands;
          if (newSimMode && d.gcode_feed?.length) {
            liveCommands = d.gcode_feed;
          } else if (!newSimMode && d.live_commands?.length) {
            liveCommands = d.live_commands;
          }

          const now = Date.now();
          const history = get().temperatureHistory;
          const lastPoint = history[history.length - 1];
          const nextHistory = !lastPoint || now - lastPoint.ts >= 1000
            ? [...history, {
                ts: now,
                extruder: Number(d.ext_temp) || 0,
                bed: Number(d.bed_temp) || 0,
                chamber: Number(d.environment?.temperature ?? get().environment.temperature) || 0,
              }].slice(-180)
            : history;

          set({
            telemetry: {
              x:               d.cmd_x         ?? 0,
              y:               d.cmd_y         ?? 0,
              z:               d.cmd_z         ?? 0,
              live_x:          d.live_x        ?? 0,
              live_y:          d.live_y        ?? 0,
              live_z:          d.live_z        ?? 0,
              extTemp:         d.ext_temp      ?? 0,
              bedTemp:         d.bed_temp      ?? 0,
              extTarget:       d.ext_target    ?? 0,
              bedTarget:       d.bed_target    ?? 0,
              state:           d.print_state   ?? "unknown",
              filename:        d.filename      ?? "",
              file_position:   d.file_position ?? 0,
              fault:           d.print_state   === "error",
              progress:        d.progress      ?? 0,
              print_duration:  d.print_duration ?? 0,
              time_remaining:  d.time_remaining ?? 0,
              speed_factor:    d.speed_factor  ?? 100,
              flow_factor:     d.flow_factor   ?? 100,
            },
            kinematics:   d.kinematics ?? {},
            thermals:     d.thermals   ?? {},
            extrusion:    d.extrusion  ?? {},
            vibration:    d.vibration  ?? get().vibration,
            quality:      d.quality    ?? get().quality,
            exclude_object: d.exclude_object ?? { objects: [], excluded_objects: [] },
            simMode:      newSimMode,
            alerts,
            liveCommands,
            temperatureHistory: nextHistory,
            ...(d.power       ? { power:            d.power       } : {}),
            ...(d.disk        ? { disk:             d.disk        } : {}),
            ...(d.environment ? { environment:       d.environment } : {}),
            ...(d.maintenance_hints !== undefined
              ? { maintenanceHints: d.maintenance_hints } : {}),
          });
        } catch { /* bad frame */ }
      };

      ws.onerror = () => ws.close();
      ws.onclose = async () => {
        set((s) => ({ telemetry: { ...s.telemetry, fault: true } }));
        const found = await huntForApiPort();
        reconnectTimer = setTimeout(connect, found ? 100 : 2000);
      };
      set({ wsRef: ws });
    };
    connect();
  },
}));

export { API, HOST };
