// Run a Klipper macro through the typed endpoint POST /api/v1/printer/macro/<name>.
// (The free-form G-code route only accepts a fixed allowlist, so user macros used to be refused.)

const NO_CONFIRM = new Set(["PAUSE", "RESUME", "CLEAR_PAUSE"]);   // mirrors the backend

export const MACRO_CONFIGS_STORAGE_KEY = "indus3d_macro_configs";

export const DEFAULT_MACRO_CONFIG = {
  group: "General",
  color: "default",   // "default" | "red" | "amber" | "green" | "blue" | "purple"
  showWhen: "always", // "always" | "idle" | "printing" | "paused"
};

export function loadMacroConfigs(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  try {
    const raw = storage?.getItem(MACRO_CONFIGS_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function saveMacroConfigs(configs, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  try {
    storage?.setItem(MACRO_CONFIGS_STORAGE_KEY, JSON.stringify(configs));
  } catch { /* private mode */ }
}

export function filterMacrosByState(macros, macroConfigs = {}, printerState = "idle") {
  if (!Array.isArray(macros)) return [];
  const state = printerState ? String(printerState).toLowerCase() : "idle";
  return macros.filter((m) => {
    const name = typeof m === "string" ? m : m?.name;
    if (!name) return false;
    const cfg = macroConfigs[name] || DEFAULT_MACRO_CONFIG;
    const showWhen = cfg.showWhen || "always";
    if (showWhen === "always") return true;
    if (showWhen === "idle") return state === "idle" || state === "standby" || state === "ready";
    if (showWhen === "printing") return state === "printing";
    if (showWhen === "paused") return state === "paused";
    return true;
  });
}

export function groupMacros(macros, macroConfigs = {}) {
  if (!Array.isArray(macros)) return {};
  const groups = {};
  for (const m of macros) {
    const name = typeof m === "string" ? m : m?.name;
    if (!name) continue;
    const cfg = macroConfigs[name] || DEFAULT_MACRO_CONFIG;
    const groupName = cfg.group || "General";
    if (!groups[groupName]) groups[groupName] = [];
    groups[groupName].push(m);
  }
  return groups;
}

export function createMacroSlice(set, get, getApi, storage = () => (typeof localStorage !== "undefined" ? localStorage : null)) {
  const post = async (name, params, confirmed) => {
    const res = await fetch(`${getApi()}/api/v1/printer/macro/${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, ...(confirmed ? { confirmed: true } : {}) }),
    });
    const body = await res.json().catch(() => ({}));
    return { res, body };
  };

  return {
    macroStatus: null,   // {name, ok, message, ts} of the last run
    macroConfigs: loadMacroConfigs(),

    setMacroConfig: (name, configUpdate) => {
      const current = get().macroConfigs || {};
      const existing = current[name] || { ...DEFAULT_MACRO_CONFIG };
      const next = {
        ...current,
        [name]: { ...existing, ...configUpdate },
      };
      set({ macroConfigs: next });
      saveMacroConfigs(next, storage());
    },

    runMacro: async (name, params = {}) => {
      const state = get().telemetry?.state;
      const busy = state === "printing" || state === "paused";
      const finish = (ok, message) => {
        const status = { name, ok, message, ts: Date.now() };
        set({ macroStatus: status });
        setTimeout(() => { if (get().macroStatus === status) set({ macroStatus: null }); }, 8000);   // fade the note
        return { ok, message };
      };
      try {
        let confirmed = false;
        if (busy && !NO_CONFIRM.has(name.toUpperCase())) {
          if (!window.confirm(`A print is ${state}. Run macro ${name} anyway?`)) return finish(false, "cancelled");
          confirmed = true;
        }
        let { res, body } = await post(name, params, confirmed);
        if (res.status === 409 && body.needs_confirmation && !confirmed) {   // the printer started meanwhile
          if (!window.confirm(`${body.error}. Run ${name} anyway?`)) return finish(false, "cancelled");
          ({ res, body } = await post(name, params, true));
        }
        if (res.ok) return finish(true, `${name} sent`);
        return finish(false, body.error || body.detail || `HTTP ${res.status}`);
      } catch (e) {
        return finish(false, String(e));
      }
    },
  };
}
