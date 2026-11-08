import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Radio, RotateCcw } from "lucide-react";
import { API, useStore } from "./store";
import { useThemeTokens } from "./theme";

// ESP8266 bed hub: chamber climate (BME280), bed vibration / jerk (ADXL345) and the crash latch,
// from the esp_bed_hub backend plugin (GET /api/v1/plugins/esp_bed_hub). The hub's host daemon is
// bound to localhost and never contacted from the browser. Renders nothing when the plugin is absent
// or disabled, so installs without the hub are unchanged.

const POLL_MS = 5000;          // the API allows 120 requests/min per client
const HISTORY_POLL_MS = 60000;
const BASE = `${API}/api/v1/plugins/esp_bed_hub`;

const fmt = (v, digits = 1, unit = "") =>
  typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(digits)}${unit}` : "—";

function Stat({ t, label, value, tone }) {
  return (
    <div className={`p-2 ${t.cell}`}>
      <span className={t.label}>{label}</span>
      <span className={tone || ""}>{value}</span>
    </div>
  );
}

// Last hour as a tiny line chart; a gap (null) where the BME280 reported nothing.
function Spark({ rows, field, label, unit, color }) {
  const pts = rows.map((r, i) => [i, r[field]]).filter(([, v]) => typeof v === "number");
  if (pts.length < 2) return null;
  const vals = pts.map(([, v]) => v);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const w = 160, h = 28, n = rows.length - 1 || 1;
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${((i / n) * w).toFixed(1)},${(h - 2 - ((v - lo) / span) * (h - 4)).toFixed(1)}`).join(" ");
  return (
    <div className="flex items-center gap-2 text-[10px] opacity-80">
      <span className="w-14 shrink-0">{label}</span>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${label} over the last hour, ${fmt(lo, 1)} to ${fmt(hi, 1)} ${unit}`}>
        <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
      <span>{fmt(lo, 1)}–{fmt(hi, 1)} {unit}</span>
    </div>
  );
}

export function BedHubCard() {
  const t = useThemeTokens();
  const printState = useStore((s) => s.telemetry?.state);
  const [data, setData] = useState(null);
  const [absent, setAbsent] = useState(false);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [threshold, setThreshold] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(BASE);
      if (res.status === 404) { setAbsent(true); return; }
      if (!res.ok) return;
      const json = await res.json();
      setAbsent(json.enabled === false);
      setData(json);
    } catch { /* backend briefly unreachable: keep the last reading */ }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/samples?minutes=60&limit=120`);
      if (res.ok) setRows((await res.json()).samples || []);
    } catch { /* optional */ }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (absent) return undefined;
    loadHistory();
    const id = setInterval(loadHistory, HISTORY_POLL_MS);
    return () => clearInterval(id);
  }, [absent, loadHistory]);

  const act = async (action, confirmText, value) => {
    if (!window.confirm(confirmText)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch(`${BASE}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, value, confirmed: true }),
      });
      const body = await res.json().catch(() => ({}));
      setMessage({ ok: res.ok, text: res.ok ? (body.message || "done") : (body.error || `HTTP ${res.status}`) });
      load();
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  if (absent || data === null) return null;

  const paused = printState === "paused";
  const ch = data.chamber || {};
  const bed = data.bed_accel || {};
  const crashed = data.crash_latched;
  const status = !data.connected ? "offline" : !data.hub_connected ? "hub unplugged" : crashed ? "crash" : "live";
  const chip = crashed ? "bg-red-500/20 text-red-400" : data.hub_connected ? "bg-emerald-500/20 text-emerald-500" : "bg-gray-500/20 opacity-70";
  const lastEvent = data.events?.[0];

  return (
    <div className={`p-4 ${t.panel}`} data-testid="bed-hub-card">
      <div className="flex items-center gap-2 mb-4 text-cyan-500">
        <Radio size={18} />
        <h3 className={t.heading}>Bed Sensor Hub</h3>
        <span className={`ml-auto text-[10px] px-2 py-0.5 ${t.chip} ${chip}`}>{status}</span>
      </div>

      {!data.hub_connected ? (
        <div className={`p-2 text-xs opacity-60 ${t.cell}`}>
          {data.connected ? "The hub daemon is running but the ESP8266 is not delivering data" : "Hub daemon not reachable"}
          {data.last_error ? ` — ${data.last_error}` : ""}. It is normal while the printer is off.
        </div>
      ) : (
        <div className="flex flex-col gap-3 font-mono text-xs">
          {crashed && (
            <div className="p-2 rounded border border-red-500/60 bg-red-500/10 text-red-400 flex items-start gap-2" role="alert">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <div>
                <div>Bed crash latched{lastEvent?.peak_jerk_mg ? ` (jerk ${lastEvent.peak_jerk_mg} mg)` : ""}{lastEvent?.action ? ` — ${lastEvent.action}` : ""}</div>
                <div className="opacity-80">{data.hold_active ? "Corrections are held. " : ""}Inspect the bed, then BED_CRASH_RESUME in the console{paused ? "" : " (the print is not paused: check Klipper)"}.</div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat t={t} label="Chamber" value={fmt(ch.temp_c, 1, " °C")} />
            <Stat t={t} label="Humidity" value={fmt(ch.humidity_pct, 0, " %")} />
            <Stat t={t} label="Pressure" value={fmt(ch.pressure_hpa, 0, " hPa")} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat t={t} label="Bed jerk" value={fmt(bed.jerk_mg, 0, " mg")} tone={bed.jerk_mg >= (data.crash_threshold_mg || 2000) * 0.5 ? "text-amber-400" : ""} />
            <Stat t={t} label="Threshold" value={fmt(data.crash_threshold_mg, 0, " mg")} />
            <Stat t={t} label="Data age" value={fmt(data.age_s, 1, " s")} />
          </div>

          <div className="flex flex-col gap-1">
            <Spark rows={rows} field="chamber_temp_c" label="Chamber" unit="°C" color="#06b6d4" />
            <Spark rows={rows} field="chamber_humidity_pct" label="Humidity" unit="%" color="#8b5cf6" />
            <Spark rows={rows} field="bed_jerk_mg" label="Jerk" unit="mg" color="#f59e0b" />
          </div>

          {data.storage?.last_error && <div className="text-[10px] text-amber-400">Telemetry not stored: {data.storage.last_error}</div>}

          <div className="border-t border-gray-500/20 pt-3 flex flex-wrap items-center gap-2">
            <button disabled={busy || !crashed} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40 flex items-center gap-1`}
              onClick={() => act("reset_crash", "Clear the hub's crash latch? Do this only after inspecting the bed.")}><RotateCcw size={11} />Reset latch</button>
            <input aria-label="Crash threshold in milligrams" placeholder={String(data.crash_threshold_mg ?? 2000)} value={threshold}
              onChange={(e) => setThreshold(e.target.value)} className={`w-16 px-1 py-1 border ${t.border} rounded bg-transparent`} inputMode="numeric" />
            <button disabled={busy || !/^\d+$/.test(threshold)} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40`}
              onClick={() => act("set_threshold", `Set the crash threshold to ${threshold} mg (500–8000)?`, Number(threshold))}>Set threshold</button>
            {message && <span className={`text-[10px] ${message.ok ? "text-emerald-500" : "text-red-400"}`}>{message.text}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
