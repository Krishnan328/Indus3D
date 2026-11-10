// UI preferences (Settings dialogs read `uiPrefs.*` and write with `setUiPref(key, value)`).
//
// store.js used to initialise `uiPrefs` from localStorage with no defaults and never defined `setUiPref`, so
// the Settings -> Control tab crashed on a fresh browser and no toggle saved. Every key the app reads is
// listed here with its default; add new keys here.

export const UI_PREFS_STORAGE_KEY = "indus3d_ui_prefs";

export const UI_PREF_DEFAULTS = {
  // confirmations
  confirmEstop: true, confirmCancelPrint: true, confirmCooldown: false, confirmPowerToggle: true,
  // console
  consoleCompact: false, consoleDirection: "bottom", hideTempsInConsole: false,
  // formats / display
  dateFormat: "browser", timeFormat: "browser", printerDisplayName: "", showProgressFavicon: true,
  // editor and files
  editorCloseOnEsc: true, editorConfirmUnsaved: true, editorTabSize: 2, hideUploadButton: false,
  // g-code viewer
  gcodeColorByHeight: true, gcodeShowAxes: true, gcodeShowTravel: false,
  // macros
  hiddenMacros: [], macroOrder: [],
  // toolhead
  invertX: false, invertY: false, invertZ: false,
  toolheadSpeedXY: 100, toolheadSpeedZ: 10, moveDistances: [0.1, 1, 10, 50],
  toolheadStyle: "bars",            // "bars" | "circle" | "cross"
  hideAxisControlsInPrint: false, combinedXYHome: true,
  extrudeAmounts: [5, 10, 25, 50], extrudeSpeeds: [2, 5, 10],      // mm and mm/s
  zOffsetSteps: [0.01, 0.025, 0.05, 0.1],
  // temperature chart
  chartColors: {}, chartSmoothing: 0, chartHidden: {}, chartOverlays: { fans: false, power: false, humidity: false },
};

// Stored values win, but a value of the wrong kind (e.g. an array where a number belongs) falls back.
export function mergePrefs(stored) {
  const out = { ...UI_PREF_DEFAULTS };
  if (stored && typeof stored === "object" && !Array.isArray(stored)) {
    for (const [key, value] of Object.entries(stored)) {
      const def = UI_PREF_DEFAULTS[key];
      if (def === undefined) { out[key] = value; continue; }          // unknown keys (older/newer builds) are kept
      const same = Array.isArray(def) ? Array.isArray(value)
        : (def && typeof def === "object") ? (value && typeof value === "object" && !Array.isArray(value))
          : typeof value === typeof def;
      if (same) out[key] = value;
    }
  }
  return out;
}

export function loadUiPrefs(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  try {
    return mergePrefs(JSON.parse(storage?.getItem(UI_PREFS_STORAGE_KEY) || "{}"));
  } catch {
    return mergePrefs({});
  }
}

export function createUiPrefsSlice(set, get, storage = () => (typeof localStorage !== "undefined" ? localStorage : null)) {
  return {
    setUiPref: (key, value) => {
      const next = { ...get().uiPrefs, [key]: value };
      set({ uiPrefs: next });
      try { storage()?.setItem(UI_PREFS_STORAGE_KEY, JSON.stringify(next)); } catch { /* private mode: keep it in memory */ }
    },
  };
}
