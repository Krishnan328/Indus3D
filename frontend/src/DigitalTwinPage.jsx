import React, { useState } from "react";
import {
  Thermometer, Database, Zap, Wind, Droplets,
  GitBranch, Cpu, Play, Pause, SkipBack, Wrench, Activity,
  CheckCircle2, Settings, Flame, Box, Download, FileText
} from "lucide-react";
import { useStore } from "./store";
import { ActionLog } from "./ActionLog";
import { PowerPanel } from "./PowerPanel";
import { TimelapseGallery } from "./TimelapseGallery";
import { ShaperTuner } from "./ShaperTuner";
import { useThemeTokens } from "./theme";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import { GripHorizontal, Lock, Unlock } from "lucide-react";
const ResponsiveGridLayout = WidthProvider(Responsive);

// ── Replay Panel ──────────────────────────────────────────────────────────────
function ReplayPanel() {
  const snapshots      = useStore((s) => s.replaySnapshots);
  const cursor         = useStore((s) => s.replayCursor);
  const playing        = useStore((s) => s.replayPlaying);
  const fetchSnapshots = useStore((s) => s.fetchReplaySnapshots);
  const setCursor      = useStore((s) => s.setReplayCursor);
  const startReplay    = useStore((s) => s.startReplay);
  const stopReplay     = useStore((s) => s.stopReplay);
  const [limit, setLimit] = useState(500);
  const t = useThemeTokens();
  const cur = snapshots[cursor] ?? null;

  return (
    <div className={`p-4 flex flex-col gap-3 ${t.panel}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-blue-400"><Play size={15} /><h3 className={t.heading}>Print Replay</h3></div>
        <div className="flex items-center gap-2">
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className={`text-[10px] px-2 py-1 ${t.cell}`}>
            {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>{n} pts</option>)}
          </select>
          <button onClick={() => fetchSnapshots(limit)} className={`text-[10px] px-3 py-1 bg-blue-700 hover:bg-blue-600 text-white font-bold uppercase tracking-widest ${t.chip}`}>Load</button>
        </div>
      </div>
      {!snapshots.length
        ? <div className="text-[11px] opacity-40 italic text-center py-4">Load snapshots from a completed print.</div>
        : <>
            <input type="range" min={0} max={snapshots.length - 1} value={cursor}
              onChange={(e) => { stopReplay(); setCursor(Number(e.target.value)); }} className="w-full accent-blue-500" />
            <div className="flex justify-between text-[10px] font-mono opacity-50 -mt-2">
              <span>0</span><span>{cursor}/{snapshots.length - 1}</span><span>{snapshots.length - 1}</span>
            </div>
            <div className="flex gap-2 justify-center">
              <button onClick={() => { stopReplay(); setCursor(0); }} className={`p-2 ${t.cell}`}><SkipBack size={14} /></button>
              <button onClick={() => playing ? stopReplay() : startReplay()}
                className={`flex items-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-widest text-white ${t.chip} ${playing ? "bg-yellow-600 hover:bg-yellow-500" : "bg-blue-600 hover:bg-blue-500"}`}>
                {playing ? <><Pause size={13} />Pause</> : <><Play size={13} />Play</>}
              </button>
            </div>
            {cur && (
              <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                {[["X", cur.cmd_x], ["Y", cur.cmd_y], ["Z", cur.cmd_z]].map(([ax, val]) => (
                  <div key={ax} className={`p-2 ${t.cell}`}><span className={t.label}>{ax}</span>{(val ?? 0).toFixed(2)}</div>
                ))}
                <div className={`p-2 ${t.cell}`}><span className={t.label}>Ext °C</span>{(cur.ext_temp ?? 0).toFixed(1)}</div>
                <div className={`p-2 ${t.cell}`}><span className={t.label}>Bed °C</span>{(cur.bed_temp ?? 0).toFixed(1)}</div>
                <div className={`p-2 ${t.cell}`}><span className={t.label}>mm/s</span>{(cur.velocity_mm_s ?? 0).toFixed(1)}</div>
              </div>
            )}
          </>
      }
    </div>
  );
}

// ── Sensor Fusion (Power + Environment) ───────────────────────────────────────
function SensorFusionCard() {
  const power       = useStore((s) => s.power);
  const environment = useStore((s) => s.environment);
  const t = useThemeTokens();
  return (
    <div className="flex flex-col gap-5">
      <div className={`p-4 ${t.panel}`}>
        <div className="flex items-center gap-2 mb-4 text-yellow-500"><Zap size={18} /><h3 className={t.heading}>Power Delivery</h3></div>
        <div className="grid grid-cols-3 gap-2 text-center font-mono text-sm">
          {power.connected === false && power.voltage == null
            ? <div className={`col-span-3 p-2 opacity-50 ${t.cell}`}>Not connected</div>
            : [["Voltage", power.voltage != null ? `${power.voltage.toFixed(1)} V` : "—"],
               ["Current", power.current != null ? `${power.current.toFixed(2)} A` : "—"],
               ["Active Load", power.power != null ? `${power.power.toFixed(1)} W` : "—"]].map(([l, v]) => (
              <div key={l} className={`p-2 ${t.cell}`}><span className={t.label}>{l}</span>{v}</div>
            ))
          }
        </div>
      </div>
      <div className={`p-4 ${t.panel}`}>
        <div className="flex items-center gap-2 mb-4 text-cyan-500"><Wind size={18} /><h3 className={t.heading}>Chamber Environment</h3></div>
        <div className="flex justify-between items-center font-mono text-sm mb-2">
          <div className="flex items-center gap-2 opacity-60 text-xs"><Thermometer size={14} />Ambient Temp</div>
          <span>{(environment.temperature ?? 0).toFixed(1)} °C</span>
        </div>
        <div className="flex justify-between items-center font-mono text-sm">
          <div className="flex items-center gap-2 opacity-60 text-xs"><Droplets size={14} />Humidity</div>
          <span>{(environment.humidity ?? 0).toFixed(1)} %</span>
        </div>
      </div>
    </div>
  );
}

// ── Digital Twin page ─────────────────────────────────────────────────────────
// Everything that doesn't fit the glanceable dashboard lives here: full
// kinematic/thermal/extrusion model internals, lifetime odometry, power/
// environment, print history, maintenance hints, and print replay. This
// page scrolls — unlike the dashboard, it's a deliberate deep-dive, not
// a glance.

function KinematicModelCard({ kinematics, telemetry, t }) {
  return (
    <div className={`h-full p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-purple-400 shrink-0"><GitBranch size={16} /><h3 className={t.heading}>Kinematic Model</h3></div>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-3">
        <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
          {["x", "y", "z"].map((a) => (
            <div key={a} className={`p-2 ${t.cell}`}><span className={t.label}>Live {a.toUpperCase()}</span>{(Number(telemetry[a]) || 0).toFixed(1)}</div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
          {["x", "y", "z"].map((a) => (
            <div key={a} className={`p-2 ${t.cell}`}><span className={t.label}>Lag {a.toUpperCase()} mm</span>{(kinematics[`lag_${a}_mm`] ?? 0).toFixed(3)}</div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Velocity mm/s</span>{(kinematics.derived_velocity_mm_s ?? 0).toFixed(1)}</div>
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Accel mm/s²</span>{(kinematics.accel_mm_s2 ?? 0).toFixed(1)}</div>
        </div>
      </div>
    </div>
  );
}

function LifetimeOdometryCard({ kinematics, t }) {
  return (
    <div className={`h-full p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-cyan-400 shrink-0"><Database size={16} /><h3 className={t.heading}>Lifetime Odometry</h3></div>
      <div className="flex-1 min-h-0 overflow-y-auto grid grid-cols-2 sm:grid-cols-4 gap-2 text-center font-mono text-xs">
        {["X", "Y", "Z", "E"].map((a) => (
          <div key={a} className={`p-2 ${t.cell}`}><span className={t.label}>{a}</span>{((kinematics.odometry_m ?? {})[a] ?? 0).toFixed(2)}m</div>
        ))}
      </div>
    </div>
  );
}

function ThermalModelCard({ thermals, t, flag }) {
  return (
    <div className={`h-full p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-orange-400 shrink-0">
        <Thermometer size={16} />
        <h3 className={t.heading}>Thermal Model{flag(thermals.ext_runaway_flag, "RUNAWAY")}{flag(thermals.bed_runaway_flag, "BED")}</h3>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 ${t.cell}`}><span className={t.label}>PID error</span>{(thermals.ext_error_c ?? 0).toFixed(2)} °C</div>
          <div className={`p-2 ${t.cell}`}><span className={t.label}>PID shadow Δ</span>{(thermals.ext_pid_delta ?? 0).toFixed(4)}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Ext cycles</span>{thermals.ext_heat_cycles ?? 0}</div>
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Bed cycles</span>{thermals.bed_heat_cycles ?? 0}</div>
        </div>
      </div>
    </div>
  );
}

function ExtrusionModelCard({ extrusion, t, flag }) {
  return (
    <div className={`h-full p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-yellow-400 shrink-0">
        <Cpu size={16} />
        <h3 className={t.heading}>Extrusion Model{flag(extrusion.under_extrusion_flag, "UNDER")}{flag(extrusion.over_extrusion_flag, "OVER")}</h3>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Vol flow mm³/s</span>{(extrusion.volumetric_flow_mm3_s ?? 0).toFixed(3)}</div>
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Flow ratio</span>{(extrusion.flow_ratio ?? 1).toFixed(2)}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 ${t.cell}`}><span className={t.label}>LA estimate</span>{(extrusion.pressure_estimate_mm ?? 0).toFixed(4)}</div>
          <div className={`p-2 ${t.cell}`}><span className={t.label}>Filament</span>{(extrusion.filament_consumed_m ?? 0).toFixed(2)} m</div>
        </div>
      </div>
    </div>
  );
}

const DEFAULT_TWIN_LAYOUTS = {
  lg: [
    { i: "kinematic", x: 0, y: 0, w: 6, h: 4 },
    { i: "shaper", x: 6, y: 0, w: 6, h: 4 },
    { i: "odometry", x: 0, y: 4, w: 6, h: 3 },
    { i: "thermal", x: 0, y: 7, w: 6, h: 4 },
    { i: "power", x: 6, y: 4, w: 6, h: 4 },
    { i: "extrusion", x: 0, y: 11, w: 6, h: 4 },
    { i: "sensor", x: 6, y: 8, w: 6, h: 7 },
    { i: "maintenance", x: 0, y: 15, w: 4, h: 4 },
    { i: "analytics", x: 4, y: 15, w: 4, h: 4 },
    { i: "spool", x: 8, y: 15, w: 4, h: 4 },
    { i: "timelapse", x: 0, y: 19, w: 4, h: 4 },
    { i: "replay", x: 4, y: 19, w: 8, h: 4 },
    { i: "actionlog", x: 0, y: 23, w: 12, h: 4 },
  ],
  md: [
    { i: "kinematic", x: 0, y: 0, w: 5, h: 4 },
    { i: "shaper", x: 5, y: 0, w: 5, h: 4 },
    { i: "odometry", x: 0, y: 4, w: 5, h: 3 },
    { i: "thermal", x: 5, y: 4, w: 5, h: 4 },
    { i: "power", x: 0, y: 7, w: 5, h: 4 },
    { i: "extrusion", x: 5, y: 8, w: 5, h: 4 },
    { i: "sensor", x: 0, y: 11, w: 5, h: 6 },
    { i: "maintenance", x: 5, y: 12, w: 5, h: 4 },
    { i: "analytics", x: 0, y: 17, w: 5, h: 4 },
    { i: "timelapse", x: 5, y: 16, w: 5, h: 4 },
    { i: "replay", x: 0, y: 21, w: 5, h: 4 },
    { i: "actionlog", x: 5, y: 20, w: 5, h: 4 },
  ],
  sm: [
    { i: "kinematic", x: 0, y: 0, w: 6, h: 4 },
    { i: "shaper", x: 0, y: 4, w: 6, h: 4 },
    { i: "odometry", x: 0, y: 8, w: 6, h: 3 },
    { i: "thermal", x: 0, y: 11, w: 6, h: 4 },
    { i: "power", x: 0, y: 15, w: 6, h: 4 },
    { i: "extrusion", x: 0, y: 19, w: 6, h: 4 },
    { i: "sensor", x: 0, y: 23, w: 6, h: 6 },
    { i: "maintenance", x: 0, y: 29, w: 6, h: 4 },
    { i: "analytics", x: 0, y: 33, w: 6, h: 4 },
    { i: "timelapse", x: 0, y: 37, w: 6, h: 4 },
    { i: "replay", x: 0, y: 41, w: 6, h: 4 },
    { i: "actionlog", x: 0, y: 45, w: 6, h: 4 },
  ]
};

function getSavedTwinLayouts() {
  try {
    const s = localStorage.getItem("indus3d_twin_layout_v1");
    if (s) return JSON.parse(s);
  } catch {
    // A malformed saved layout should fall back to the default arrangement.
  }
  return DEFAULT_TWIN_LAYOUTS;
}

function CardWrapper({ children, isLocked }) {
  return (
    <div className={`h-full flex flex-col overflow-hidden ${!isLocked ? "ring-2 ring-emerald-500 rounded-xl" : ""}`}>
      {!isLocked && (
        <div className="drag-handle cursor-grab active:cursor-grabbing bg-emerald-500 text-white flex items-center justify-center py-1 absolute top-0 left-0 right-0 z-50 opacity-0 hover:opacity-100 transition-opacity">
          <GripHorizontal size={16} />
        </div>
      )}
      <div className="flex-1 min-h-0 h-full" style={{ paddingTop: !isLocked ? "4px" : "0" }}>
        {children}
      </div>
    </div>
  );
}



function MaintenancePanel() {
  const hints = useStore((s) => s.maintenanceHints);
  const status = useStore((s) => s.maintenanceStatus) || [];
  const config = useStore((s) => s.maintenanceConfig) || {};
  const updateConfig = useStore((s) => s.updateMaintenanceConfig);
  const t = useThemeTokens();

  const [showConfig, setShowConfig] = useState(false);

  const formatName = (m) => m.replace(/_/g, " ").replace("odometry", "Odo").toUpperCase();

  const handleReset = async (metric) => {
    try {
      await fetch(useStore.getState().API + "/api/v1/maintenance/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: metric })
      });
      // Slight delay to allow backend to write before refreshing
      setTimeout(() => useStore.getState().fetchSensorData(), 500);
    } catch (e) {
      console.error(e);
    }
  };

  const consumables = status.filter(s => s.type === "consumable");
  const mechanical = status.filter(s => s.type !== "consumable");

  return (
    <div className={`h-full p-4 flex flex-col ${t.panel} relative`}>
      <div className="flex items-center gap-2 mb-3 shrink-0">
        <Wrench size={16} className="text-emerald-400" />
        <h3 className={t.heading}>Maintenance & Wear</h3>
        <button
          onClick={() => setShowConfig(!showConfig)}
          className="ml-auto opacity-50 hover:opacity-100 transition-opacity"
        >
          <Settings size={14} />
        </button>
      </div>

      {showConfig ? (
        <div className={`absolute inset-0 z-10 p-4 flex flex-col ${t.panel} bg-black/90 backdrop-blur-sm`}>
          <div className="flex justify-between items-center mb-4">
            <h4 className="text-[12px] font-bold text-white">Component Profiles</h4>
            <button onClick={() => setShowConfig(false)} className="text-[10px] text-emerald-400 font-bold uppercase tracking-wider">Done</button>
          </div>

          <div className="flex flex-col gap-3 overflow-y-auto">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase font-bold opacity-70">Nozzle Material</label>
              <select
                value={config.nozzle_material || "Brass"}
                onChange={(e) => updateConfig({ nozzle_material: e.target.value })}
                className={`text-[11px] p-1.5 rounded outline-none ${t.cell}`}
              >
                {["Brass", "Plated Copper", "Stainless Steel", "Hardened Steel", "Tungsten Carbide", "Ruby-tipped", "Diamond-tipped"].map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase font-bold opacity-70">Filament Abrasiveness</label>
              <select
                value={config.filament_type || "Standard"}
                onChange={(e) => updateConfig({ filament_type: e.target.value })}
                className={`text-[11px] p-1.5 rounded outline-none ${t.cell}`}
              >
                <option value="Standard">Standard (PLA/PETG/ABS)</option>
                <option value="Abrasive">Abrasive (CF/GF/Glow)</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase font-bold opacity-70">Structural Material</label>
              <select
                value={config.structural_material || "PETG"}
                onChange={(e) => updateConfig({ structural_material: e.target.value })}
                className={`text-[11px] p-1.5 rounded outline-none ${t.cell}`}
              >
                {["PLA", "PETG", "ABS", "ASA", "PC", "Nylon", "Machined Aluminum", "Machined Steel"].map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      ) : null}

      {status.length === 0 ? (
        <div className="text-[11px] opacity-40 italic text-center flex-1 flex items-center justify-center">All systems nominal</div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto pr-2 flex flex-col gap-4">

          {/* Consumables Section */}
          <div className="flex flex-col gap-3">
            <h4 className="text-[10px] uppercase font-bold text-yellow-500 tracking-widest border-b border-white/10 pb-1">Consumables</h4>
            <div className="grid grid-cols-2 gap-3">
              {consumables.map((item, i) => {
                const pct = Math.min(100, Math.max(0, (item.value / item.threshold) * 100));
                const isCritical = pct >= 90;
                const isWarn = pct >= 70 && !isCritical;

                let Icon = Box;
                if (item.metric.includes("nozzle")) Icon = Flame;
                if (item.metric.includes("filter")) Icon = Wind;

                return (
                  <div key={i} className={`flex flex-col gap-2 p-2 rounded-lg ${t.cell} border ${isCritical ? 'border-red-500/50' : 'border-white/5'}`}>
                    <div className="flex justify-between items-start">
                      <Icon size={14} className={isCritical ? "text-red-400" : isWarn ? "text-yellow-400" : "text-emerald-400"} />
                      <button onClick={() => handleReset(item.metric)} className="text-[9px] uppercase font-bold opacity-50 hover:opacity-100 text-blue-400 transition-colors">Replace</button>
                    </div>
                    <div>
                      <div className="text-[12px] font-bold font-mono leading-none">{item.value.toFixed(1)} <span className="text-[9px] font-sans opacity-50">/ {item.threshold}h</span></div>
                      <div className="text-[9px] opacity-70 truncate">{formatName(item.metric)}</div>
                    </div>
                    {/* Thick progress bar */}
                    <div className="h-2 w-full bg-black/40 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${isCritical ? "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" : isWarn ? "bg-yellow-500" : "bg-emerald-500"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Mechanical / Odometry Section */}
          <div className="flex flex-col gap-2">
            <h4 className="text-[10px] uppercase font-bold opacity-50 tracking-widest border-b border-white/10 pb-1 flex justify-between">
              <span>Mechanical Odometry</span>
              {hints.length > 0 && <span className="text-yellow-500">{hints.length} Warnings</span>}
            </h4>
            <div className="space-y-2">
              {mechanical.map((item, i) => {
                const pct = Math.min(100, Math.max(0, (item.value / item.threshold) * 100));
                const isCritical = pct >= 90;
                const isWarn = pct >= 70 && !isCritical;
                return (
                  <div key={i} className="flex flex-col gap-1 group">
                    <div className="flex justify-between items-center text-[10px]">
                      <span className="font-mono font-bold opacity-70">{formatName(item.metric)}</span>
                      <div className="flex items-center gap-2">
                        <span className={`font-mono ${isCritical ? "text-red-400 font-bold" : "opacity-50"}`}>
                          {item.value.toFixed(1)} / {item.threshold}
                        </span>
                        <button onClick={() => handleReset(item.metric)} className="hover:text-emerald-400 opacity-0 group-hover:opacity-100 transition-all" title="Reset Counter">
                          <CheckCircle2 size={12} />
                        </button>
                      </div>
                    </div>
                    <div className={`h-1 w-full rounded-full overflow-hidden ${t.cell}`}>
                      <div
                        className={`h-full ${isCritical ? "bg-red-500" : isWarn ? "bg-yellow-500" : "bg-blue-500"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}


function AnalyticsCard() {
  const history = useStore((s) => s.printHistory);
  const t = useThemeTokens();

  const completed = history.filter((h) => h.status === "completed").length;
  const failed = history.filter((h) => h.status !== "completed").length;
  const total = history.length;
  const failPercent = total ? Math.round((failed / total) * 100) : 0;
  const successPercent = total ? 100 - failPercent : 0;

  const downloadReport = (reportPath) => {
    window.open(`${useStore.getState().API}/api/v1/reports/${reportPath}`, '_blank');
  };

  return (
    <div className={`h-full p-4 flex flex-col ${t.panel} relative`}>
      <h3 className={`${t.heading} mb-3 shrink-0 flex items-center gap-2 text-indigo-400`}><Activity size={16}/> Print Analytics & QA</h3>
      {!total ? (
        <div className="text-xs opacity-50 italic flex-1 flex items-center justify-center">No history available</div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto pr-2">

          {/* Top Stats */}
          <div className="flex flex-row gap-4 items-center sm:items-start justify-center shrink-0">
            <div className="relative w-20 h-20 shrink-0 flex items-center justify-center">
              <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90 drop-shadow-lg">
                <circle cx="18" cy="18" r="15.915" fill="transparent" stroke="#22c55e" strokeWidth="4" />
                {failPercent > 0 && (
                  <circle
                    cx="18" cy="18" r="15.915" fill="transparent"
                    stroke="#ef4444" strokeWidth="4"
                    strokeDasharray={`${failPercent} ${100 - failPercent}`}
                  />
                )}
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="text-sm font-bold">{successPercent}%</span>
                <span className="text-[7px] uppercase tracking-widest opacity-60">Success</span>
              </div>
            </div>

            <div className="flex-1 flex flex-col justify-center text-xs font-mono space-y-1.5 w-full">
              <div className={`flex justify-between p-1.5 rounded ${t.cell}`}>
                <span className="opacity-70">Total Prints</span>
                <span className="font-bold">{total}</span>
              </div>
              <div className={`flex justify-between p-1.5 rounded ${t.cell}`}>
                <span className="opacity-70 text-emerald-400">Completed</span>
                <span className="font-bold">{completed}</span>
              </div>
              <div className={`flex justify-between p-1.5 rounded ${t.cell}`}>
                <span className="opacity-70 text-red-400">Failed/Halted</span>
                <span className="font-bold">{failed}</span>
              </div>
            </div>
          </div>

          {/* QA Reports List */}
          <div className="flex flex-col gap-2">
            <h4 className="text-[10px] uppercase font-bold opacity-50 tracking-widest border-b border-white/10 pb-1">Recent QA Reports</h4>
            <div className="flex flex-col gap-2">
              {history.slice(0, 5).map((job, i) => (
                <div key={i} className={`flex items-center justify-between p-2 rounded ${t.cell} text-[10px]`}>
                  <div className="flex flex-col truncate pr-2">
                    <span className="font-bold truncate" title={job.filename}>{job.filename || "Unknown Job"}</span>
                    <span className="opacity-50 text-[9px]">{new Date(job.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={job.status === 'completed' ? 'text-emerald-400' : 'text-red-400'}>
                      {job.status === 'completed' ? 'PASS' : 'FAIL'}
                    </span>
                    {job.report_path ? (
                      <button
                        onClick={() => downloadReport(job.report_path)}
                        className="p-1 rounded bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-colors"
                        title="Download QA Report (PDF)"
                      >
                        <FileText size={12} />
                      </button>
                    ) : (
                      <span className="p-1 opacity-20" title="No QA report available"><FileText size={12} /></span>
                    )}
                    {job.annotated_gcode_path ? (
                      <button
                        onClick={() => downloadReport(job.annotated_gcode_path)}
                        className="p-1 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500 hover:text-white transition-colors ml-1"
                        title="Download Annotated G-code (PDF)"
                      >
                        <Download size={12} />
                      </button>
                    ) : (
                      <span className="p-1 opacity-20 ml-1" title="No annotated G-code available"><Download size={12} /></span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}


 // Wait, make sure we import it or use a default one like Database.

function VirtualSpoolPanel() {
  const config = useStore((s) => s.maintenanceConfig) || {};
  const updateConfig = useStore((s) => s.updateMaintenanceConfig);
  const t = useThemeTokens();

  const totalG = parseFloat(config.virtual_spool_weight_g || "1000");
  const usedG = parseFloat(config.virtual_spool_used_g || "0");
  const color = config.virtual_spool_color || "#ef4444";
  const material = config.virtual_spool_material || "PLA";

  const remainingG = Math.max(0, totalG - usedG);
  const pct = Math.max(0, Math.min(100, (remainingG / totalG) * 100));

  const [isEditing, setIsEditing] = useState(false);
  const [editTotal, setEditTotal] = useState(totalG);
  const [editColor, setEditColor] = useState(color);
  const [editMat, setEditMat] = useState(material);

  const handleSave = () => {
    updateConfig({
      virtual_spool_weight_g: editTotal.toString(),
      virtual_spool_used_g: "0",
      virtual_spool_color: editColor,
      virtual_spool_material: editMat
    });
    setIsEditing(false);
  };

  return (
    <div className={`h-full p-4 flex flex-col ${t.panel} relative`}>
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h3 className={`${t.heading} flex items-center gap-2 text-pink-400`}><Database size={16}/> Virtual Spool</h3>
        <button onClick={() => setIsEditing(!isEditing)} className="opacity-50 hover:opacity-100 text-[10px] uppercase font-bold tracking-wider text-pink-400">
          {isEditing ? "Cancel" : "Change Spool"}
        </button>
      </div>

      {isEditing ? (
        <div className="flex-1 flex flex-col gap-2 overflow-y-auto">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase font-bold opacity-70">Material</label>
            <input type="text" value={editMat} onChange={e => setEditMat(e.target.value)} className={`text-[11px] p-1.5 rounded outline-none ${t.cell}`} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase font-bold opacity-70">Color</label>
            <input type="color" value={editColor} onChange={e => setEditColor(e.target.value)} className={`w-full h-8 rounded outline-none ${t.cell} cursor-pointer`} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase font-bold opacity-70">Total Weight (g)</label>
            <input type="number" value={editTotal} onChange={e => setEditTotal(e.target.value)} className={`text-[11px] p-1.5 rounded outline-none ${t.cell}`} />
          </div>
          <button onClick={handleSave} className="mt-2 p-1.5 bg-pink-500 hover:bg-pink-400 text-white text-[11px] font-bold rounded">Save & Reset Used</button>
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-4">
          <div className="relative w-24 h-24 shrink-0 flex items-center justify-center">
            <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90 drop-shadow-lg">
              <circle cx="18" cy="18" r="15.915" fill="transparent" stroke="rgba(255,255,255,0.1)" strokeWidth="4" />
              <circle
                cx="18" cy="18" r="15.915" fill="transparent"
                stroke={color} strokeWidth="4"
                strokeDasharray={`${pct} ${100 - pct}`}
                className="transition-all duration-1000"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-lg font-bold font-mono">{pct.toFixed(0)}%</span>
              <span className="text-[8px] uppercase tracking-widest opacity-60" style={{ color }}>{material}</span>
            </div>
          </div>
          <div className="flex justify-between w-full text-xs font-mono px-4">
            <div className="flex flex-col items-center">
              <span className="opacity-50">Remaining</span>
              <span className="font-bold text-pink-400">{remainingG.toFixed(1)}g</span>
            </div>
            <div className="flex flex-col items-center">
              <span className="opacity-50">Used</span>
              <span className="font-bold">{usedG.toFixed(1)}g</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


export function DigitalTwinPage({ isDarkMode }) {
  const kinematics = useStore((s) => s.kinematics);
  const thermals   = useStore((s) => s.thermals);
  const extrusion  = useStore((s) => s.extrusion);
  const telemetry  = useStore((s) => s.telemetry);
  const t = useThemeTokens();

  const [layouts, setLayouts] = useState(getSavedTwinLayouts);
  const [isLocked, setIsLocked] = useState(true);

  const onLayoutChange = (layout, allLayouts) => {
    setLayouts(allLayouts);
    localStorage.setItem("indus3d_twin_layout_v1", JSON.stringify(allLayouts));
  };

  const resetLayout = () => {
    localStorage.removeItem("indus3d_twin_layout_v1");
    setLayouts(DEFAULT_TWIN_LAYOUTS);
  };

  const flag = (active, text) => active
    ? <span className="ml-2 px-2 py-0.5 bg-red-600 text-white text-[9px] font-bold rounded-full animate-pulse">{text}</span>
    : null;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 flex flex-col">
      <div className="flex justify-end gap-2 mb-2 shrink-0">
        {!isLocked && (
          <button onClick={resetLayout} className="text-xs px-2 py-1 rounded bg-red-500/20 text-red-500 hover:bg-red-500/40">
            Reset Default Layout
          </button>
        )}
        <button
          onClick={() => setIsLocked(!isLocked)}
          className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${isLocked ? 'bg-gray-500/10 text-gray-400 hover:bg-gray-500/20' : 'bg-emerald-500 text-white'}`}
        >
          {isLocked ? <><Lock size={12}/> Unlock Dashboard</> : <><Unlock size={12}/> Lock Layout</>}
        </button>
      </div>

      <div className="flex-1 min-h-0 pb-10">
        <ResponsiveGridLayout
          className="layout"
          layouts={layouts}
          breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
          cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
          rowHeight={60}
          onLayoutChange={onLayoutChange}
          draggableHandle=".drag-handle"
          isDraggable={!isLocked}
          isResizable={!isLocked}
          margin={[12, 12]}
        >
          <div key="kinematic"><CardWrapper isLocked={isLocked}><KinematicModelCard kinematics={kinematics} telemetry={telemetry} t={t} /></CardWrapper></div>
          <div key="shaper"><CardWrapper isLocked={isLocked}><ShaperTuner /></CardWrapper></div>
          <div key="odometry"><CardWrapper isLocked={isLocked}><LifetimeOdometryCard kinematics={kinematics} t={t} /></CardWrapper></div>
          <div key="thermal"><CardWrapper isLocked={isLocked}><ThermalModelCard thermals={thermals} t={t} flag={flag} /></CardWrapper></div>
          <div key="power"><CardWrapper isLocked={isLocked}><PowerPanel isDarkMode={isDarkMode} /></CardWrapper></div>
          <div key="extrusion"><CardWrapper isLocked={isLocked}><ExtrusionModelCard extrusion={extrusion} t={t} flag={flag} /></CardWrapper></div>
          <div key="sensor"><CardWrapper isLocked={isLocked}><SensorFusionCard /></CardWrapper></div>
          <div key="maintenance"><CardWrapper isLocked={isLocked}><MaintenancePanel /></CardWrapper></div>
          <div key="analytics"><CardWrapper isLocked={isLocked}><AnalyticsCard /></CardWrapper></div>
          <div key="spool"><CardWrapper isLocked={isLocked}><VirtualSpoolPanel /></CardWrapper></div>
          <div key="timelapse"><CardWrapper isLocked={isLocked}><TimelapseGallery /></CardWrapper></div>
          <div key="replay"><CardWrapper isLocked={isLocked}><ReplayPanel /></CardWrapper></div>
          <div key="actionlog"><CardWrapper isLocked={isLocked}><ActionLog isDarkMode={isDarkMode} /></CardWrapper></div>
        </ResponsiveGridLayout>
      </div>
    </div>
  );
}
