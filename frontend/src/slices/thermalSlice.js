// Temperature chart data and the Moonraker Sensors card.
//
// * `thermalLive`   per-series buffers {id: {t, v}} of the last 5 minutes, appended from the printer-status
//                   poll (see recordThermalSample; the chart calls it whenever printerStatus.ts changes).
// * `thermalHistory` a backfill from GET /api/v1/printer/thermal_history for the selected range.
// * `thermalSensors` rows from GET /api/v1/printer/sensors (Moonraker sensors, bed hub fallback).
// Colours live in uiPrefs.chartColors and are mirrored to the server preferences (syncPreference), so they
// follow the user to another browser.

import { appendSample, historyToSeries, liveSample, LIVE_KEEP_S } from "./thermalLogic.js";

export function createThermalSlice(set, get, getApi) {
  let historySeq = 0;
  let colorsRestored = false;

  return {
    thermalLive: {},
    thermalHistory: { minutes: 0, series: {}, loading: false, error: null, sources: null, chamberSource: null },
    thermalSensors: { loaded: false, ok: false, error: null, sensors: [] },

    recordThermalSample: () => {
      const { printerStatus, environment } = get();
      if (!printerStatus?.ok) return;
      const sample = liveSample(printerStatus, environment);
      set({ thermalLive: appendSample(get().thermalLive, sample, Date.now() / 1000, LIVE_KEEP_S) });
    },

    // Latest request wins: switching range quickly never lets a slow answer overwrite a newer one.
    fetchThermalHistory: async (minutes) => {
      const seq = ++historySeq;
      set({ thermalHistory: { ...get().thermalHistory, minutes, loading: true, error: null } });
      try {
        const res = await fetch(`${getApi()}/api/v1/printer/thermal_history?minutes=${encodeURIComponent(minutes)}`);
        const body = await res.json().catch(() => ({}));
        if (seq !== historySeq) return;
        if (res.ok && body.ok) {
          set({ thermalHistory: { minutes, now: body.now, series: historyToSeries(body), loading: false, error: null,
            sources: body.sources || null, chamberSource: body.chamber_source || null } });
        } else {
          set({ thermalHistory: { minutes, series: {}, loading: false, error: body.error || `HTTP ${res.status}`,
            sources: body.sources || null, chamberSource: null } });
        }
      } catch (e) {
        if (seq === historySeq) set({ thermalHistory: { minutes, series: {}, loading: false, error: String(e), sources: null, chamberSource: null } });
      }
    },

    fetchMoonrakerSensors: async () => {
      try {
        const res = await fetch(`${getApi()}/api/v1/printer/sensors`);
        const body = await res.json().catch(() => ({}));
        if (res.ok && body.ok) set({ thermalSensors: { loaded: true, ok: true, error: null, sensors: body.sensors || [] } });
        else set({ thermalSensors: { ...get().thermalSensors, loaded: true, ok: false, error: body.error || `HTTP ${res.status}` } });
      } catch (e) {
        set({ thermalSensors: { ...get().thermalSensors, loaded: true, ok: false, error: String(e) } });
      }
    },

    setChartColor: (id, color) => {
      const next = { ...(get().uiPrefs.chartColors || {}) };
      if (color) next[id] = color; else delete next[id];
      get().setUiPref("chartColors", next);
      get().syncPreference("chartColors", JSON.stringify(next));
    },

    // Once per session: take the colours saved on the server when this browser has none of its own.
    restoreChartColors: async () => {
      if (colorsRestored) return;
      colorsRestored = true;
      if (Object.keys(get().uiPrefs.chartColors || {}).length) return;
      try {
        const res = await fetch(`${getApi()}/api/v1/profile/preferences`);
        if (!res.ok) return;
        const prefs = await res.json();
        const parsed = typeof prefs.chartColors === "string" ? JSON.parse(prefs.chartColors) : null;
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) get().setUiPref("chartColors", parsed);
      } catch { /* the defaults are fine */ }
    },
  };
}
