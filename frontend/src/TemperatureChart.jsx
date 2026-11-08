import React, { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Thermometer } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";
import { ThermalLegend } from "./thermal/ThermalLegend";
import {
  RANGES, SMOOTHING_OPTIONS, align, clip, colorFor, fallbackCatalog, fallbackSamples, isVisible, mergeSeries,
  seriesCatalog, smooth, tempCeiling, withHistoryDefs,
} from "./slices/thermalLogic";

// Temperature chart: every heater (with its target), temperature sensor / fan and, optionally, fan speeds and
// heater power, taken from Klipper's object status. uPlot is loaded on first use (it is the only reason this
// card would add weight to the dashboard bundle).
const ThermalPlot = lazy(() => import("./thermal/ThermalPlot"));
const NO_HIDDEN = {};
const HISTORY_REFRESH_MS = 60000;

// Overlays are drawn translucent so they read as secondary to the temperature lines.
const withAlpha = (hex, id) => (/\.(power|speed)$/.test(id) && /^#[0-9a-f]{6}$/i.test(hex) ? `${hex}99` : hex);

export function TemperatureChart() {
  const t = useThemeTokens();
  const printerStatus = useStore((s) => s.printerStatus);
  const environment = useStore((s) => s.environment);
  const temperatureHistory = useStore((s) => s.temperatureHistory);
  const extTarget = useStore((s) => s.telemetry?.extTarget);
  const bedTarget = useStore((s) => s.telemetry?.bedTarget);
  const thermalLive = useStore((s) => s.thermalLive);
  const thermalHistory = useStore((s) => s.thermalHistory);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const setUiPref = useStore((s) => s.setUiPref);
  const setChartColor = useStore((s) => s.setChartColor);
  const subscribePrinterStatus = useStore((s) => s.subscribePrinterStatus);
  const recordThermalSample = useStore((s) => s.recordThermalSample);
  const fetchThermalHistory = useStore((s) => s.fetchThermalHistory);
  const restoreChartColors = useStore((s) => s.restoreChartColors);

  const [rangeId, setRangeId] = useState("1m");
  const [focusId, setFocusId] = useState(null);
  const range = RANGES.find((r) => r.id === rangeId) || RANGES[0];
  const spanS = range.minutes * 60;
  const hidden = uiPrefs.chartHidden || NO_HIDDEN;
  const overlays = uiPrefs.chartOverlays || NO_HIDDEN;
  const colors = uiPrefs.chartColors || NO_HIDDEN;
  const smoothing = Number(uiPrefs.chartSmoothing) || 0;

  useEffect(() => subscribePrinterStatus(), [subscribePrinterStatus]);          // polls only while the card is mounted
  useEffect(() => { restoreChartColors(); }, [restoreChartColors]);
  useEffect(() => { recordThermalSample(); }, [printerStatus.ts, recordThermalSample]);
  useEffect(() => {
    fetchThermalHistory(range.minutes);
    if (range.live) return undefined;
    const id = setInterval(() => fetchThermalHistory(range.minutes), HISTORY_REFRESH_MS);
    return () => clearInterval(id);
  }, [range.minutes, range.live, fetchThermalHistory]);

  const klipperOk = printerStatus.ok;
  const view = useMemo(() => {
    const live = klipperOk ? thermalLive : fallbackSamples(temperatureHistory, extTarget, bedTarget);
    const backfill = thermalHistory.minutes === range.minutes ? thermalHistory.series : {};
    const merged = mergeSeries(backfill, live);
    const catalog = withHistoryDefs(klipperOk ? seriesCatalog(printerStatus, environment) : fallbackCatalog(), Object.keys(merged));
    const parents = catalog.filter((d) => d.group === "heater" || d.group === "sensor");
    const defs = catalog.filter((d) => merged[d.id]?.t.length && isVisible(d, hidden, overlays) && !(d.parent && hidden[d.parent]));
    const colourOf = (d) => {
      const base = d.parent || d.id;
      const index = Math.max(0, parents.findIndex((p) => p.id === base));
      return withAlpha(colorFor(d.id, colors, d.parent ? index : (index || catalog.indexOf(d))), d.id);
    };
    const newest = Math.max(0, ...defs.map((d) => merged[d.id].t[merged[d.id].t.length - 1]));
    const shown = {};
    for (const d of defs) {
      const s = d.group === "target" ? merged[d.id] : smooth(merged[d.id], smoothing);
      shown[d.id] = clip(s, newest, spanS);
    }
    const { x, ys } = align(shown, defs.map((d) => d.id));
    const plotDefs = defs.map((d) => ({ id: d.id, label: d.label, axis: d.axis, dashed: d.dashed, color: colourOf(d) }));
    const tempCols = ys.filter((_, i) => defs[i].axis === "temp");
    const chips = parents.filter((d) => merged[d.id]?.t.length || d.group === "heater").map((d) => {
      const last = (id) => { const s = merged[id]; return s?.v.length ? s.v[s.v.length - 1] : undefined; };
      return { def: d, color: colourOf(d), value: last(d.id), target: last(`${d.id}.target`) };
    });
    return { x, ys, plotDefs, chips, ceiling: tempCeiling(tempCols), hasData: x.length > 1 };
  }, [klipperOk, thermalLive, thermalHistory, range.minutes, spanS, printerStatus, environment, temperatureHistory,
    extTarget, bedTarget, hidden, overlays, colors, smoothing]);

  const toggleSeries = (id) => setUiPref("chartHidden", { ...hidden, [id]: !hidden[id] });
  const toggleOverlay = (key) => setUiPref("chartOverlays", { ...overlays, [key]: !overlays[key] });
  const hasOverlay = (key) => (printerStatus.capabilities?.[key] || []).length > 0;
  const chip = (on) => `px-2 py-0.5 text-[10px] font-bold ${t.chip} ${on ? "bg-blue-600 text-white" : t.cell}`;
  const mr = thermalHistory.sources?.moonraker;
  const storeMinutes = !range.live && mr?.ok && mr.from && thermalHistory.now ? Math.round((thermalHistory.now - mr.from) / 60) : null;
  const customColours = Object.keys(colors).length > 0;

  return (
    <section className={`h-full min-h-[250px] flex flex-col p-4 ${t.panel}`}>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-center gap-2 text-orange-400"><Thermometer size={16} /><h3 className={t.heading}>Temperatures</h3></div>
        <div className="flex gap-1" role="group" aria-label="Time range">
          {RANGES.map((r) => <button key={r.id} onClick={() => setRangeId(r.id)} aria-pressed={rangeId === r.id} className={chip(rangeId === r.id)}>{r.label}</button>)}
        </div>
      </div>
      <ThermalLegend items={view.chips} hidden={hidden} onToggle={toggleSeries} onFocus={setFocusId} onColor={setChartColor} focusId={focusId} t={t} />
      <div className="flex items-center gap-2 mb-1 flex-wrap text-[10px]">
        <label className="flex items-center gap-1 opacity-80">Smoothing
          <select value={smoothing} onChange={(e) => setUiPref("chartSmoothing", Number(e.target.value))} aria-label="Smoothing window"
            className="bg-transparent border border-current/20 rounded px-1 py-0.5">
            {SMOOTHING_OPTIONS.map((s) => <option key={s} value={s} className="text-black">{s === 0 ? "None" : `${s} s`}</option>)}
          </select>
        </label>
        {hasOverlay("heaters") && <button onClick={() => toggleOverlay("power")} aria-pressed={!!overlays.power} className={chip(!!overlays.power)}>Heater power</button>}
        {hasOverlay("fans") && <button onClick={() => toggleOverlay("fans")} aria-pressed={!!overlays.fans} className={chip(!!overlays.fans)}>Fans</button>}
        {(view.plotDefs.some((d) => d.id.endsWith("humidity")) || environment?.humidity > 0) && (
          <button onClick={() => toggleOverlay("humidity")} aria-pressed={!!overlays.humidity} className={chip(!!overlays.humidity)}>Humidity</button>
        )}
        {customColours && <button onClick={() => Object.keys(colors).forEach((id) => setChartColor(id, null))} className="underline opacity-60">Reset colours</button>}
        <span className="ml-auto opacity-50">drag to zoom · double-click to reset</span>
      </div>
      <div className="flex-1 min-h-[120px] relative">
        {view.hasData ? (
          <Suspense fallback={<div className="absolute inset-0 flex items-center justify-center text-xs italic opacity-45">Loading chart…</div>}>
            <ThermalPlot x={view.x} ys={view.ys} defs={view.plotDefs} hidden={NO_HIDDEN} focusId={focusId} onFocus={setFocusId}
              ceiling={view.ceiling} spanS={spanS} />
          </Suspense>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs italic opacity-45 text-center px-4">
            {thermalHistory.loading ? "Loading history…" : thermalHistory.error && !range.live ? `History unavailable: ${thermalHistory.error}` : "Collecting temperature history…"}
          </div>
        )}
      </div>
      {!klipperOk && <div className="mt-1 text-[9px] opacity-50">Klipper status unavailable{printerStatus.error ? ` (${printerStatus.error})` : ""}: showing extruder, bed and chamber only.</div>}
      {thermalHistory.chamberSource === "esp_bed_hub" && !range.live && <div className="mt-1 text-[9px] opacity-50">Chamber from the ESP8266 hub (no Klipper chamber sensor).</div>}
      {storeMinutes != null && storeMinutes < range.minutes * 0.9 && (
        <div className="mt-1 text-[9px] opacity-50">Heater power, fans and sensors are only kept by Moonraker for about the last {storeMinutes} min; extruder and bed go back further.</div>
      )}
    </section>
  );
}
