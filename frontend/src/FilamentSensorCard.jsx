import React, { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, Gauge, RotateCcw, Ruler, Weight } from "lucide-react";
import { API, useStore } from "./store";
import { useThemeTokens } from "./theme";

// Smart filament sensor: live diameter / flow / spool / runout, plus the
// calibration actions. Everything comes from the filament_sensor backend
// plugin (GET /api/v1/plugins/filament_sensor); the daemon itself is bound to
// localhost and never contacted from the browser. The card renders nothing when
// the plugin is absent or disabled, so installs without the sensor are unchanged.

const POLL_MS = 5000;   // the API allows 120 requests/min per client; keep the dashboard well under it
const ENDPOINT = `${API}/api/v1/plugins/filament_sensor`;

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

export function FilamentSensorCard() {
  const t = useThemeTokens();
  const printState = useStore((s) => s.telemetry?.state);
  const [data, setData] = useState(null);       // null = not loaded yet
  const [absent, setAbsent] = useState(false);  // plugin missing / disabled
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [span, setSpan] = useState("1.75");

  const load = useCallback(async () => {
    try {
      const res = await fetch(ENDPOINT);
      if (res.status === 404) { setAbsent(true); return; }
      if (!res.ok) return;
      const json = await res.json();
      setAbsent(json.enabled === false);
      setData(json);
    } catch { /* backend briefly unreachable: keep the last reading */ }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const act = async (action, confirmText, extra = {}) => {
    if (!window.confirm(confirmText)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch(`${ENDPOINT}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, confirmed: true, ...extra }),
      });
      const body = await res.json().catch(() => ({}));
      setMessage({ ok: res.ok, text: res.ok ? (body.message || `${action.replace("_", " ")} done`) : (body.error || `HTTP ${res.status}`) });
      load();
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  if (absent || data === null) return null;

  const printing = printState === "printing" || printState === "paused";
  const faulted = data.faults && data.faults !== "NORMAL";
  const countdown = data.runout_countdown_mm || 0;
  const spoolTotal = (data.spool_used_g ?? 0) + (data.spool_remaining_g ?? 0);
  const spoolPct = spoolTotal > 0 ? Math.max(0, Math.min(100, (data.spool_remaining_g / spoolTotal) * 100)) : 0;
  const lastSync = data.spool_sync?.recent?.[0];

  return (
    <div className={`p-4 ${t.panel}`} data-testid="filament-sensor-card">
      <div className="flex items-center gap-2 mb-4 text-emerald-500">
        <Activity size={18} />
        <h3 className={t.heading}>Filament Sensor</h3>
        <span className={`ml-auto text-[10px] px-2 py-0.5 ${t.chip} ${data.connected ? "bg-emerald-500/20 text-emerald-500" : "bg-gray-500/20 opacity-70"}`}>
          {data.connected ? (data.fresh ? "live" : "stale") : "offline"}
        </span>
      </div>

      {!data.connected ? (
        <div className={`p-2 text-xs opacity-60 ${t.cell}`}>
          Sensor daemon not reachable{data.last_error ? ` — ${data.last_error}` : ""}. It is normal while the printer is off.
        </div>
      ) : (
        <div className="flex flex-col gap-3 font-mono text-xs">
          {(faulted || data.filament_present === false || countdown > 0) && (
            <div className="p-2 rounded border border-red-500/60 bg-red-500/10 text-red-400 flex items-start gap-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <div>
                {faulted && <div>Fault: {data.faults}</div>}
                {data.filament_present === false && <div>No filament at the sensor{countdown > 0 ? ` — ${countdown.toFixed(0)} mm left in the Bowden tube` : ""}</div>}
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat t={t} label="Diameter at sensor" value={fmt(data.diameter_mm, 3, " mm")} />
            <Stat t={t} label="Diameter at nozzle" value={fmt(data.nozzle_diameter_mm, 3, " mm")} />
            <Stat t={t} label="Flow at nozzle" value={fmt(data.nozzle_flow_mm3_s, 2, " mm³/s")} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat t={t} label="Filament speed" value={fmt(data.velocity_mm_s, 1, " mm/s")} />
            <Stat t={t} label="Sensor auto-flow" value={data.flow_owned_by_sensor ? fmt(data.auto_flow_percent, 1, " %") : "off"} />
            <Stat t={t} label="Bowden buffer" value={fmt(data.bowden_buffered_mm, 0, " mm")} />
          </div>

          <div className={`p-2 ${t.cell}`}>
            <div className="flex items-center justify-between mb-1">
              <span className={`${t.label} !mb-0 flex items-center gap-1`}><Weight size={11} />Spool</span>
              <span>{fmt(data.spool_remaining_g, 0, " g")} left · {fmt(data.spool_used_g, 1, " g")} used</span>
            </div>
            <div className="h-1.5 rounded bg-gray-500/20 overflow-hidden" role="progressbar" aria-valuenow={Math.round(spoolPct)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-emerald-500" style={{ width: `${spoolPct}%` }} />
            </div>
            {lastSync && (
              <div className="mt-1 text-[10px] opacity-60">
                {lastSync.applied
                  ? `Last print: ${lastSync.measured_g} g measured (estimate ${lastSync.estimated_g} g) — recorded`
                  : `Last print not recorded from the sensor: ${lastSync.reason}`}
              </div>
            )}
          </div>

          {data.flow_input && data.flow_input !== "off" && (
            <div className="text-[10px] opacity-60 flex items-center gap-1"><Gauge size={11} />Measured flow drives the controller: {data.flow_input}</div>
          )}

          {data.events?.length > 0 && (
            <div className="text-[10px] opacity-70 flex flex-col gap-0.5">
              {data.events.slice(0, 3).map((e) => (
                <div key={`${e.ts}-${e.kind}`}>{new Date(e.ts * 1000).toLocaleTimeString()} · {e.detail}</div>
              ))}
            </div>
          )}

          <div className="border-t border-gray-500/20 pt-3 flex flex-col gap-2">
            <span className={`${t.label} !mb-0 flex items-center gap-1`}><Ruler size={11} />Calibration</span>
            {printing && <div className="text-[10px] opacity-60">Disabled during a print.</div>}
            <div className="flex flex-wrap items-center gap-2">
              <button disabled={busy || printing} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40`}
                onClick={() => act("tare_empty", "Tare the empty bearings (remove the filament first). Continue?")}>Tare empty</button>
              <input aria-label="Calibration diameter in millimetres" value={span} onChange={(e) => setSpan(e.target.value)}
                className={`w-16 px-1 py-1 border ${t.border} rounded bg-transparent`} inputMode="decimal" />
              <button disabled={busy || printing} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40`}
                onClick={() => act("calibrate_span", `Calibrate the span to ${span} mm with a known-diameter filament in the sensor. Continue?`, { target: Number(span) })}>Calibrate span</button>
              <button disabled={busy || printing} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40 flex items-center gap-1`}
                onClick={() => act("reset_spool", "Reset the measured spool usage to 0 g (use when you load a new spool). Continue?")}><RotateCcw size={11} />Reset spool</button>
              <button disabled={busy || printing} className={`px-2 py-1 border ${t.border} rounded disabled:opacity-40`}
                onClick={() => act("reset_bowden", "Clear the Bowden-tube diameter buffer? Do this after unloading filament. Continue?")}>Reset Bowden</button>
            </div>
            {message && <div className={`text-[10px] ${message.ok ? "text-emerald-500" : "text-red-400"}`}>{message.text}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
