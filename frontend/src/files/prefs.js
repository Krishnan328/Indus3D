import { DEFAULT_FILTERS } from "./filesLogic.js";

const KEY = "indus3d_fm_prefs_v1";
const DEFAULTS = { sort: { key: "name", dir: "asc" }, filters: DEFAULT_FILTERS, view: "list", thumb: 40 };

// Per-viewer conveniences only (sort, filters, view, thumbnail size). Everything is wrapped: storage can be
// blocked or empty and the file manager must work without it.
export function loadFmPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return {
      sort: { ...DEFAULTS.sort, ...(raw.sort || {}) },
      filters: { ...DEFAULTS.filters, ...(raw.filters || {}) },
      view: raw.view === "grid" ? "grid" : "list",
      thumb: Math.max(24, Math.min(160, Number(raw.thumb) || DEFAULTS.thumb)),
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveFmPrefs(prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* storage unavailable: preferences just are not remembered */ }
}
