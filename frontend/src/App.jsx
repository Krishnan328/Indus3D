import React, { useState, useEffect, useRef } from "react";
import {
  Activity, Thermometer, Box, Camera, Sun, Moon,
  Database, Zap, Wind, Droplets, FileText, Save,
  RefreshCw, X, Map, AlertTriangle, Cpu, GitBranch,
  Play, Pause, SkipBack, Bell, Wrench,
} from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Line, Environment, GizmoHelper, GizmoViewcube } from "@react-three/drei";
import { useStore } from "./store";
import { PrintBed } from "./PrintBed";
import { ProfileBar } from "./ProfileBar";
import { PrintStatusCard } from "./PrintStatusCard";
import { ActionLog } from "./ActionLog";
import { QualityPanel } from "./QualityPanel";
import { GCodeVisualizer } from "./GCodeVisualizer";
import * as THREE from "three";

const originalConsoleWarn = console.warn;
console.warn = (...args) => {
  if (typeof args[0] === "string" && args[0].includes("THREE.Clock")) return;
  originalConsoleWarn(...args);
};

// ─────────────────────────────────────────────────────────────────────────────
// ALERT BAR
// ─────────────────────────────────────────────────────────────────────────────
function AlertBar({ isDarkMode }) {
  const alerts       = useStore((s) => s.alerts);
  const dismissAlert = useStore((s) => s.dismissAlert);
  if (!alerts.length) return null;
  const colours = {
    critical: "bg-red-600 border-red-500 text-white",
    warn:     "bg-yellow-600 border-yellow-500 text-white",
    info:     "bg-blue-700 border-blue-500 text-white",
  };
  return (
    <div className="flex flex-col gap-1 mb-2">
      {alerts.map((a) => (
        <div key={a.id} className={`flex items-center justify-between px-4 py-2 rounded-lg border text-xs font-bold tracking-wide ${colours[a.level] ?? colours.info} ${a.level === "critical" ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2"><AlertTriangle size={14} />{a.msg}</div>
          <button onClick={() => dismissAlert(a.id)} className="ml-4 opacity-70 hover:opacity-100"><X size={13} /></button>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAINTENANCE PANEL
// ─────────────────────────────────────────────────────────────────────────────
function MaintenancePanel({ isDarkMode }) {
  const hints = useStore((s) => s.maintenanceHints);
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  return (
    <div className={`p-4 rounded-xl border ${inner}`}>
      <div className="flex items-center gap-2 mb-3 text-yellow-400">
        <Wrench size={16} />
        <h3 className="font-semibold tracking-wide uppercase text-sm">Maintenance</h3>
        {hints.length > 0 && (
          <span className="ml-auto px-2 py-0.5 bg-yellow-600 text-white text-[9px] font-bold rounded-full animate-pulse">
            {hints.length} due
          </span>
        )}
      </div>
      {hints.length === 0 ? (
        <div className="text-[11px] opacity-40 italic text-center py-3">✓ All systems nominal</div>
      ) : (
        <div className="flex flex-col gap-2">
          {hints.map((h, i) => (
            <div key={i} className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${isDarkMode ? "bg-yellow-900/20 border border-yellow-700/40 text-yellow-300" : "bg-yellow-50 border border-yellow-200 text-yellow-800"}`}>
              <Wrench size={11} className="mt-0.5 shrink-0" />{h}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// REPLAY PANEL
// ─────────────────────────────────────────────────────────────────────────────
function ReplayPanel({ isDarkMode }) {
  const snapshots      = useStore((s) => s.replaySnapshots);
  const cursor         = useStore((s) => s.replayCursor);
  const playing        = useStore((s) => s.replayPlaying);
  const fetchSnapshots = useStore((s) => s.fetchReplaySnapshots);
  const setCursor      = useStore((s) => s.setReplayCursor);
  const startReplay    = useStore((s) => s.startReplay);
  const stopReplay     = useStore((s) => s.stopReplay);
  const [limit, setLimit] = useState(500);
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const cell  = isDarkMode ? "bg-gray-900 border-gray-800 text-gray-200" : "bg-white border-gray-200 text-gray-800";
  const label = "text-[9px] uppercase tracking-widest block mb-1 opacity-60";
  const current = snapshots[cursor] ?? null;
  return (
    <div className={`p-4 rounded-xl border flex flex-col gap-3 ${inner}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-blue-400"><Play size={15} /><h3 className="font-semibold tracking-wide uppercase text-sm">Print Replay</h3></div>
        <div className="flex items-center gap-2">
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className={`text-[10px] px-2 py-1 rounded border ${cell}`}>
            {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>{n} pts</option>)}
          </select>
          <button onClick={() => fetchSnapshots(limit)} className="text-[10px] px-3 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded font-bold uppercase tracking-widest">Load</button>
        </div>
      </div>
      {snapshots.length === 0 ? (
        <div className="text-[11px] opacity-40 italic text-center py-4">Load snapshots from a completed print.</div>
      ) : (
        <>
          <input type="range" min={0} max={snapshots.length - 1} value={cursor}
            onChange={(e) => { stopReplay(); setCursor(Number(e.target.value)); }} className="w-full accent-blue-500" />
          <div className="flex justify-between text-[10px] font-mono opacity-50 -mt-2">
            <span>0</span><span>{cursor}/{snapshots.length - 1}</span><span>{snapshots.length - 1}</span>
          </div>
          <div className="flex gap-2 justify-center">
            <button onClick={() => { stopReplay(); setCursor(0); }} className={`p-2 rounded-lg border ${cell} hover:border-blue-500`}><SkipBack size={14} /></button>
            <button onClick={() => playing ? stopReplay() : startReplay()}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-widest text-white transition-all ${playing ? "bg-yellow-600 hover:bg-yellow-500" : "bg-blue-600 hover:bg-blue-500"}`}>
              {playing ? <><Pause size={13} />Pause</> : <><Play size={13} />Play</>}
            </button>
          </div>
          {current && (
            <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
              {[["X", current.cmd_x], ["Y", current.cmd_y], ["Z", current.cmd_z]].map(([ax, val]) => (
                <div key={ax} className={`p-2 rounded border ${cell}`}><span className={label}>{ax}</span>{(val ?? 0).toFixed(2)}</div>
              ))}
              <div className={`p-2 rounded border ${cell}`}><span className={label}>Ext °C</span>{(current.ext_temp ?? 0).toFixed(1)}</div>
              <div className={`p-2 rounded border ${cell}`}><span className={label}>Bed °C</span>{(current.bed_temp ?? 0).toFixed(1)}</div>
              <div className={`p-2 rounded border ${cell}`}><span className={label}>mm/s</span>{(current.velocity_mm_s ?? 0).toFixed(1)}</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 3D SCENE
// ─────────────────────────────────────────────────────────────────────────────
function Toolhead() {
  const fault      = useStore((s) => s.telemetry.fault);
  const isPrinting = useStore((s) => s.telemetry.state === "printing");
  const bed        = useStore((s) => s.bed);
  const meshRef    = useRef();
  const ox = (bed.origin_center ? 0 : (bed.size_x_mm ?? 300) / 2) / 10;
  const oz = (bed.origin_center ? 0 : (bed.size_y_mm ?? 300) / 2) / 10;

  useFrame(() => {
    const { x, y, z } = useStore.getState().telemetry;
    if (!meshRef.current) return;
    meshRef.current.position.x = THREE.MathUtils.lerp(meshRef.current.position.x, (Number(x) || 0) / 10, 0.2);
    meshRef.current.position.y = THREE.MathUtils.lerp(meshRef.current.position.y, (Number(z) || 0) / 10 + 0.9, 0.2);
    meshRef.current.position.z = THREE.MathUtils.lerp(meshRef.current.position.z, (Number(y) || 0) / 10, 0.2);
  });

  const color = fault ? "#ef4444" : isPrinting ? "#3b82f6" : "#578396";
  return (
    <mesh ref={meshRef} position={[ox, 0.9, oz]}>
      <cylinderGeometry args={[0.15, 0.15, 1.2, 32]} />
      <meshPhysicalMaterial color={color} transmission={1} ior={1.5} thickness={1.5} roughness={0.15} transparent />
      <mesh position={[0, -0.75, 0]} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[0.15, 0.3, 32]} />
        <meshStandardMaterial color={isPrinting ? "#fbbf24" : "#9ca3af"} metalness={0.9} roughness={0.2}
          emissive={isPrinting ? "#fbbf24" : "#000000"} emissiveIntensity={0.6} />
      </mesh>
    </mesh>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SIDEBAR PANELS
// ─────────────────────────────────────────────────────────────────────────────
function Terminal({ isDarkMode }) {
  const [input, setInput] = useState("");
  const [isSending, setSending] = useState(false);
  const filePosition = useStore((s) => s.telemetry.file_position);
  const gcodeLines   = useStore((s) => s.gcodeLines);
  const simMode      = useStore((s) => s.simMode);
  const [liveFeed, setLiveFeed] = useState({ lines: [], activeIdx: -1 });

  useEffect(() => {
    if (!gcodeLines?.length) { setLiveFeed({ lines: [], activeIdx: -1 }); return; }
    if (simMode) {
      const lines = gcodeLines.slice(-5);
      setLiveFeed({ lines, activeIdx: lines.length - 1 });
      return;
    }
    try {
      let lo = 0, hi = gcodeLines.length - 1, mid = 0;
      const pos = Number(filePosition) || 0;
      while (lo <= hi) {
        mid = Math.floor((lo + hi) / 2);
        if (!gcodeLines[mid]) break;
        if (gcodeLines[mid].byte < pos) lo = mid + 1;
        else if (gcodeLines[mid].byte > pos) hi = mid - 1;
        else break;
      }
      const start = Math.max(0, mid - 2), end = Math.min(gcodeLines.length, mid + 3);
      setLiveFeed({ lines: gcodeLines.slice(start, end), activeIdx: mid - start });
    } catch {}
  }, [filePosition, gcodeLines, simMode]);

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    setSending(true);
    try {
      const HOST = window.location.hostname;
      await fetch(`http://${HOST}:5001/api/control/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: input.trim(), source: "frontend" }),
      });
      setInput("");
    } catch {}
    setSending(false);
  };

  const inner    = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const inputCls = isDarkMode ? "bg-gray-900 text-green-400 border-gray-700" : "bg-white text-gray-800 border-gray-300";
  return (
    <div className={`p-4 rounded-xl border flex flex-col gap-3 ${inner}`}>
      <div className="flex items-center gap-2 text-emerald-500">
        <Activity size={18} />
        <h3 className="font-semibold tracking-wide uppercase text-sm">G-Code Terminal</h3>
        {simMode && <span className="ml-auto text-[9px] px-2 py-0.5 bg-blue-700 text-white rounded-full font-bold">SIM — type TEST</span>}
      </div>
      <div className={`h-28 p-2 rounded-lg font-mono text-[10px] overflow-y-auto flex flex-col-reverse shadow-inner ${isDarkMode ? "bg-black border border-gray-800 text-gray-500" : "bg-gray-100 border border-gray-300 text-gray-400"}`}>
        {liveFeed.lines.length === 0
          ? <div className="text-center italic opacity-50 self-center">Awaiting Print Job...</div>
          : [...liveFeed.lines].reverse().map((l, i) => (
              <div key={i} className={`whitespace-nowrap px-1 rounded ${i === 0 ? (isDarkMode ? "text-green-400 font-bold" : "text-green-700 font-bold") : ""}`}>
                {l?.text || ";"}
              </div>
            ))}
      </div>
      <form onSubmit={send} className="flex gap-2 mt-1">
        <input type="text" value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder={simMode ? "e.g. G28 or TEST" : "e.g. G28"} disabled={isSending}
          className={`flex-1 px-3 py-2 rounded-lg border font-mono text-sm outline-none transition-colors shadow-inner ${inputCls}`} />
        <button type="submit" disabled={isSending || !input.trim()}
          className={`px-4 py-2 rounded-lg font-bold text-xs tracking-widest uppercase transition-all ${isSending ? "bg-gray-500 text-gray-300" : "bg-emerald-600 hover:bg-emerald-500 text-white shadow-md"}`}>
          {isSending ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}

function DigitalTwinPanel({ isDarkMode }) {
  const kinematics = useStore((s) => s.kinematics);
  const thermals   = useStore((s) => s.thermals);
  const extrusion  = useStore((s) => s.extrusion);
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const cell  = isDarkMode ? "bg-gray-900 border-gray-800 text-gray-200" : "bg-white border-gray-200 text-gray-800 shadow-sm";
  const label = "text-[9px] uppercase tracking-widest block mb-1 opacity-60";
  const flagBadge = (active, text) => active
    ? <span className="ml-2 px-2 py-0.5 bg-red-600 text-white text-[9px] font-bold rounded-full animate-pulse">{text}</span>
    : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Kinematic model */}
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-3 text-purple-400"><GitBranch size={16} /><h3 className="font-semibold tracking-wide uppercase text-sm">Kinematic Model</h3></div>
        <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs mb-3">
          {["x", "y", "z"].map((a) => (
            <div key={a} className={`p-2 rounded border ${cell}`}><span className={label}>Lag {a.toUpperCase()} mm</span>{(kinematics[`lag_${a}_mm`] ?? 0).toFixed(3)}</div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Velocity mm/s</span>{(kinematics.derived_velocity_mm_s ?? 0).toFixed(1)}</div>
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Accel mm/s²</span>{(kinematics.accel_mm_s2 ?? 0).toFixed(1)}</div>
        </div>
      </div>

      {/* Odometry */}
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-3 text-cyan-400"><Database size={16} /><h3 className="font-semibold tracking-wide uppercase text-sm">Lifetime Odometry</h3></div>
        <div className="grid grid-cols-4 gap-2 text-center font-mono text-xs">
          {["X", "Y", "Z", "E"].map((a) => (
            <div key={a} className={`p-2 rounded border ${cell}`}><span className={label}>{a}</span>{((kinematics.odometry_m ?? {})[a] ?? 0).toFixed(2)}m</div>
          ))}
        </div>
      </div>

      {/* Thermal model */}
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-3 text-orange-400">
          <Thermometer size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-sm">
            Thermal Model
            {flagBadge(thermals.ext_runaway_flag, "RUNAWAY")}
            {flagBadge(thermals.bed_runaway_flag, "BED RUNAWAY")}
          </h3>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs mb-2">
          <div className={`p-2 rounded border ${cell}`}><span className={label}>PID error</span>{(thermals.ext_error_c ?? 0).toFixed(2)} °C</div>
          <div className={`p-2 rounded border ${cell}`}><span className={label}>PID shadow Δ</span>{(thermals.ext_pid_delta ?? 0).toFixed(4)}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Ext cycles</span>{thermals.ext_heat_cycles ?? 0}</div>
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Bed cycles</span>{thermals.bed_heat_cycles ?? 0}</div>
        </div>
      </div>

      {/* Extrusion model */}
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-3 text-yellow-400">
          <Cpu size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-sm">
            Extrusion Model
            {flagBadge(extrusion.under_extrusion_flag, "UNDER")}
            {flagBadge(extrusion.over_extrusion_flag, "OVER")}
          </h3>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs mb-2">
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Flow mm³/s</span>{(extrusion.volumetric_flow_mm3_s ?? 0).toFixed(3)}</div>
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Ratio</span>{(extrusion.flow_ratio ?? 1).toFixed(2)}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs">
          <div className={`p-2 rounded border ${cell}`}><span className={label}>LA pressure</span>{(extrusion.pressure_estimate_mm ?? 0).toFixed(4)}</div>
          <div className={`p-2 rounded border ${cell}`}><span className={label}>Filament</span>{(extrusion.filament_consumed_m ?? 0).toFixed(2)} m</div>
        </div>
      </div>

      {/* NEW: Quality control panel */}
      <QualityPanel isDarkMode={isDarkMode} />

      <MaintenancePanel isDarkMode={isDarkMode} />
      <ActionLog isDarkMode={isDarkMode} />
      <ReplayPanel isDarkMode={isDarkMode} />
    </div>
  );
}

function SensorFusionCard({ isDarkMode }) {
  const power       = useStore((s) => s.power);
  const environment = useStore((s) => s.environment);
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const cell  = isDarkMode ? "bg-gray-900 border-gray-800 text-gray-200" : "bg-white border-gray-200 text-gray-800";
  return (
    <div className="flex flex-col gap-5">
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-4 text-yellow-500"><Zap size={18} /><h3 className="font-semibold tracking-wide uppercase text-sm">Power Delivery</h3></div>
        <div className="grid grid-cols-3 gap-2 text-center font-mono text-sm">
          {[["Voltage", `${(power.voltage ?? 0).toFixed(1)} V`], ["Current", `${(power.current ?? 0).toFixed(2)} A`], ["Active Load", `${(power.power ?? 0).toFixed(1)} W`]].map(([lbl, val]) => (
            <div key={lbl} className={`p-2 rounded border ${cell}`}>
              <span className="block text-[9px] text-gray-500 mb-1 tracking-widest uppercase">{lbl}</span>{val}
            </div>
          ))}
        </div>
      </div>
      <div className={`p-4 rounded-xl border ${inner}`}>
        <div className="flex items-center gap-2 mb-4 text-cyan-500"><Wind size={18} /><h3 className="font-semibold tracking-wide uppercase text-sm">Chamber Environment</h3></div>
        <div className="flex justify-between items-center font-mono text-sm mb-2">
          <div className="flex items-center gap-2 text-gray-500 text-xs"><Thermometer size={14} />Ambient Temp</div>
          <span className={isDarkMode ? "text-gray-200" : "text-gray-800"}>{(environment.temperature ?? 0).toFixed(1)} °C</span>
        </div>
        <div className="flex justify-between items-center font-mono text-sm">
          <div className="flex items-center gap-2 text-gray-500 text-xs"><Droplets size={14} />Humidity</div>
          <span className={isDarkMode ? "text-gray-200" : "text-gray-800"}>{(environment.humidity ?? 0).toFixed(1)} %</span>
        </div>
      </div>
    </div>
  );
}

function AnalyticsCard({ isDarkMode }) {
  const history = useStore((s) => s.printHistory);
  const card = isDarkMode ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200";
  return (
    <div className={`p-4 rounded-xl border ${card}`}>
      <h3 className="text-sm font-semibold uppercase mb-2">Print History</h3>
      {!history.length
        ? <div className="text-xs opacity-50 italic">No history available</div>
        : <div className="text-xs font-mono space-y-1">
            {history.slice(-5).map((item, i) => (
              <div key={i} className="flex justify-between gap-2">
                <span className="truncate flex-1">{item.filename || "unknown"}</span>
                <span className={`shrink-0 font-bold ${item.status === "completed" ? "text-green-500" : "text-yellow-500"}`}>{item.status || "—"}</span>
              </div>
            ))}
          </div>
      }
    </div>
  );
}

function HeightmapModal({ isDarkMode, onClose }) {
  const [meshData, setMeshData]     = useState([]);
  const [calibDate, setCalibDate]   = useState("Unknown");
  const [needsRecal, setNeedsRecal] = useState(false);
  const [isCalibrating, setCalib]   = useState(false);

  useEffect(() => {
    const HOST = window.location.hostname;
    const saved = localStorage.getItem("indus3d_mesh_date");
    if (saved) { setCalibDate(new Date(saved).toLocaleDateString()); if ((new Date() - new Date(saved)) / 86400000 > 14) setNeedsRecal(true); }
    else setNeedsRecal(true);
    (async () => {
      try { const res = await fetch(`http://${HOST}:7125/printer/objects/query?bed_mesh`); const data = await res.json(); setMeshData(data.result.status.bed_mesh.profiles.default.points); }
      catch { const mock = []; for (let i = 0; i < 5; i++) mock.push(Array.from({ length: 5 }, (_, j) => Math.sin(i) * 0.1 + Math.cos(j) * 0.1)); setMeshData(mock); }
    })();
  }, []);

  const handleCalibrate = async () => {
    const HOST = window.location.hostname;
    setCalib(true);
    try { await fetch(`http://${HOST}:7125/printer/gcode/script?script=BED_MESH_CALIBRATE`, { method: "POST" }); const today = new Date().toISOString(); localStorage.setItem("indus3d_mesh_date", today); setCalibDate(new Date(today).toLocaleDateString()); setNeedsRecal(false); setTimeout(() => { setCalib(false); onClose(); }, 2000); }
    catch { setCalib(false); }
  };

  const bg = isDarkMode ? "bg-gray-950 text-gray-200" : "bg-white text-gray-800";
  const border = isDarkMode ? "border-gray-800" : "border-gray-300";
  const MeshVoxels = () => {
    if (!meshData.length) return null;
    const sz = meshData.length, sp = 12 / sz;
    return (<group>{meshData.flatMap((row, z) => row.map((h, x) => { const color = h > 0.05 ? "#ef4444" : h < -0.05 ? "#3b82f6" : "#22c55e"; return (<mesh key={`${x}-${z}`} position={[x * sp - 6, h * 10, z * sp - 6]}><boxGeometry args={[sp * 0.8, 0.2, sp * 0.8]} /><meshStandardMaterial color={color} /></mesh>); }))}</group>);
  };
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-10 bg-black/70 backdrop-blur-md">
      <div className={`w-full max-w-4xl rounded-2xl border flex flex-col shadow-2xl ${bg} ${border} overflow-hidden`} style={{ height: "80vh" }}>
        <div className={`px-6 py-4 border-b flex justify-between items-center ${isDarkMode ? "bg-gray-900 border-gray-800" : "bg-gray-50 border-gray-200"}`}>
          <div className="flex items-center gap-3 text-emerald-500"><Map size={20} /><h2 className="font-bold tracking-widest uppercase">Surface Topography</h2></div>
          <button onClick={onClose} className="p-2 rounded-full hover:bg-red-500 hover:text-white transition-colors"><X size={20} /></button>
        </div>
        <div className="flex flex-1 overflow-hidden">
          <div className={`w-64 shrink-0 p-6 border-r flex flex-col gap-6 ${border} ${isDarkMode ? "bg-gray-900/50" : "bg-gray-50"}`}>
            <div>
              <h3 className="text-xs font-bold text-gray-500 tracking-widest uppercase mb-2">Calibration Tracker</h3>
              <div className={`p-4 rounded-xl border ${needsRecal ? "bg-yellow-900/20 border-yellow-700/50 text-yellow-500" : isDarkMode ? "bg-gray-900 border-gray-700 text-gray-300" : "bg-white border-gray-200"}`}>
                <span className="block text-[10px] uppercase tracking-widest opacity-70 mb-1">Last Probed</span>
                <span className="font-mono text-lg font-bold">{calibDate}</span>
                {needsRecal && <div className="flex items-center gap-2 mt-3 text-xs font-bold animate-pulse"><AlertTriangle size={14} />MESH OUTDATED</div>}
              </div>
            </div>
            <button onClick={handleCalibrate} disabled={isCalibrating}
              className={`mt-auto flex items-center justify-center gap-2 w-full py-3 rounded-xl font-bold text-xs uppercase tracking-widest transition-all ${isCalibrating ? "bg-gray-600 text-gray-300" : "bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg"}`}>
              <RefreshCw size={16} className={isCalibrating ? "animate-spin" : ""} />
              {isCalibrating ? "Probing..." : "Run Auto-Level"}
            </button>
          </div>
          <div className="flex-1 bg-black/90" style={{ minHeight: "400px" }}>
            <Canvas camera={{ position: [0, 15, 20], fov: 45 }} style={{ width: "100%", height: "100%" }}>
              <ambientLight intensity={0.5} /><directionalLight position={[10, 20, 10]} intensity={1.5} />
              <MeshVoxels /><OrbitControls makeDefault enableDamping dampingFactor={0.2} />
            </Canvas>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConfigEditor({ isDarkMode, onClose }) {
  const [files, setFiles]           = useState([]);
  const [selectedFile, setSelected] = useState("printer.cfg");
  const [content, setContent]       = useState("");
  const [isSaving, setSaving]       = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);
  const HOST = window.location.hostname;

  useEffect(() => { (async () => { try { const res = await fetch(`http://${HOST}:7125/server/files/list?root=config`); if (res.ok) { const data = await res.json(); setFiles(data.result.filter(f => f.path.endsWith(".cfg") || f.path.endsWith(".conf")).map(f => f.path)); } } catch {} })(); }, []);
  useEffect(() => { if (!selectedFile) return; (async () => { try { const res = await fetch(`http://${HOST}:7125/server/files/config/${selectedFile}?t=${Date.now()}`); if (res.ok) { setContent(await res.text()); setSaveStatus(null); } } catch {} })(); }, [selectedFile]);

  const handleSave = async () => { setSaving(true); try { const fd = new FormData(); fd.append("file", new Blob([content], { type: "text/plain" }), selectedFile); fd.append("root", "config"); const res = await fetch(`http://${HOST}:7125/server/files/upload`, { method: "POST", body: fd }); setSaveStatus(res.ok ? "Saved!" : "Failed."); setTimeout(() => setSaveStatus(null), 3000); } catch { setSaveStatus("Error."); } setSaving(false); };
  const handleRestart = async () => { try { await fetch(`http://${HOST}:7125/printer/gcode/script?script=FIRMWARE_RESTART`, { method: "POST" }); setSaveStatus("Restarting..."); } catch {} };

  const bg = isDarkMode ? "bg-gray-950 text-gray-200" : "bg-white text-gray-800";
  const border = isDarkMode ? "border-gray-800" : "border-gray-300";
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-10 bg-black/60 backdrop-blur-sm">
      <div className={`w-full max-w-6xl h-full max-h-[85vh] rounded-2xl border flex flex-col shadow-2xl ${bg} ${border} overflow-hidden`}>
        <div className={`px-6 py-4 border-b flex justify-between items-center ${isDarkMode ? "bg-gray-900 border-gray-800" : "bg-gray-50 border-gray-200"}`}>
          <div className="flex items-center gap-3 text-blue-500"><FileText size={20} /><h2 className="font-bold tracking-widest uppercase">Configuration Editor</h2></div>
          <button onClick={onClose} className="p-2 rounded-full hover:bg-red-500 hover:text-white transition-colors"><X size={20} /></button>
        </div>
        <div className="flex flex-1 overflow-hidden">
          <div className={`w-64 border-r flex flex-col p-2 overflow-y-auto ${border} ${isDarkMode ? "bg-gray-900/50" : "bg-gray-50"}`}>
            <h3 className="text-xs font-bold text-gray-500 tracking-widest uppercase mb-3 px-2 mt-2">Config Files</h3>
            {files.length === 0 && <div className="text-xs opacity-40 italic px-2">Not connected to printer</div>}
            {files.map((f) => (
              <button key={f} onClick={() => setSelected(f)}
                className={`text-left px-3 py-2 rounded-lg text-sm font-mono mb-1 transition-colors ${selectedFile === f ? (isDarkMode ? "bg-blue-600/20 text-blue-400 font-bold" : "bg-blue-100 text-blue-700 font-bold") : isDarkMode ? "hover:bg-gray-800 text-gray-400" : "hover:bg-gray-200 text-gray-600"}`}>
                {f}
              </button>
            ))}
          </div>
          <div className="flex-1 flex flex-col relative">
            <textarea value={content} onChange={(e) => setContent(e.target.value)} spellCheck={false}
              className={`flex-1 w-full p-6 font-mono text-sm outline-none resize-none ${isDarkMode ? "bg-[#0d1117] text-[#c9d1d9]" : "bg-white text-gray-900"}`} style={{ tabSize: 4 }} />
            <div className={`absolute bottom-6 right-6 flex gap-3 p-2 rounded-xl border backdrop-blur-md ${isDarkMode ? "bg-gray-900/80 border-gray-700" : "bg-white/80 border-gray-300 shadow-lg"}`}>
              <span className="flex items-center px-4 text-xs font-bold font-mono text-emerald-500">{saveStatus}</span>
              <button onClick={handleSave} disabled={isSaving} className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-bold text-xs uppercase tracking-widest"><Save size={16} />{isSaving ? "Saving..." : "Save File"}</button>
              <button onClick={handleRestart} className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg font-bold text-xs uppercase tracking-widest"><RefreshCw size={16} />Firmware Restart</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SIDEBAR
// ─────────────────────────────────────────────────────────────────────────────
function Sidebar({ isDarkMode }) {
  const telemetry = useStore((s) => s.telemetry);
  const [tab, setTab] = useState("dash");
  const card  = isDarkMode ? "bg-gray-900 border-gray-800" : "bg-white border-gray-300 shadow-md";
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const cell  = isDarkMode ? "bg-gray-900 border-gray-800 text-gray-200" : "bg-white border-gray-200 text-gray-800 shadow-sm";
  const tabCls = (t) => `flex-1 py-2 text-xs font-bold uppercase tracking-widest transition-colors rounded-lg ${tab === t ? (isDarkMode ? "bg-gray-700 text-white" : "bg-gray-200 text-gray-900") : (isDarkMode ? "text-gray-500 hover:text-gray-300" : "text-gray-400 hover:text-gray-700")}`;
  const HOST = window.location.hostname;

  return (
    <div className={`w-96 border-l p-6 flex flex-col gap-5 z-10 transition-colors duration-300 overflow-y-auto ${card}`}>
      <h2 className="text-xs text-gray-500 uppercase tracking-widest font-bold border-b border-gray-500/30 pb-2 shrink-0">Dashboard</h2>
      <div className={`flex gap-1 p-1 rounded-xl border ${inner}`}>
        <button className={tabCls("dash")} onClick={() => setTab("dash")}>Live</button>
        <button className={tabCls("twin")} onClick={() => setTab("twin")}>Digital Twin</button>
      </div>
      {tab === "dash" && (
        <>
          <PrintStatusCard isDarkMode={isDarkMode} />
          <div className={`p-2 rounded-xl border ${inner}`}>
            <div className="flex items-center gap-2 mb-2 px-2 pt-1 text-gray-400"><Camera size={16} /><h3 className="font-semibold tracking-wide uppercase text-xs">Live Feed</h3></div>
            <div className="relative w-full aspect-video bg-gray-950 rounded-lg overflow-hidden flex items-center justify-center border border-gray-800/50">
              <img src={`http://${HOST}/webcam/?action=stream`} alt="Live Cam" className="w-full h-full object-cover" onError={(e) => { e.target.style.display = "none"; }} />
            </div>
          </div>
          <SensorFusionCard isDarkMode={isDarkMode} />
          <Terminal isDarkMode={isDarkMode} />
          <AnalyticsCard isDarkMode={isDarkMode} />
          <div className={`p-5 rounded-xl border ${inner}`}>
            <div className="flex items-center gap-2 mb-4 text-blue-500"><Box size={18} /><h3 className="font-semibold tracking-wide uppercase text-sm">Kinematics</h3></div>
            <div className="grid grid-cols-3 gap-3 text-center font-mono text-lg">
              {[["X Axis", "text-red-500", telemetry.x], ["Y Axis", "text-green-500", telemetry.y], ["Z Axis", "text-blue-500", telemetry.z]].map(([lbl, col, val]) => (
                <div key={lbl} className={`p-3 rounded-lg border ${cell}`}><span className={`${col} block text-[10px] mb-1 tracking-widest uppercase`}>{lbl}</span>{(Number(val) || 0).toFixed(1)}</div>
              ))}
            </div>
          </div>
          <div className={`p-5 rounded-xl border ${inner}`}>
            <div className="flex items-center gap-2 mb-4 text-orange-500"><Thermometer size={18} /><h3 className="font-semibold tracking-wide uppercase text-sm">Thermals</h3></div>
            {[["EXTRUDER", telemetry.extTemp], ["HEATED BED", telemetry.bedTemp]].map(([lbl, val]) => (
              <div key={lbl} className={`flex justify-between items-center font-mono text-sm ${lbl === "EXTRUDER" ? "mb-3" : ""}`}>
                <span className="text-gray-500 tracking-wider text-xs font-semibold">{lbl}</span>
                <span className={`text-lg px-3 py-1 rounded border ${isDarkMode ? "text-gray-100 bg-gray-900 border-gray-800" : "text-gray-800 bg-white border-gray-200 shadow-sm"}`}>{(Number(val) || 0).toFixed(1)} °C</span>
              </div>
            ))}
          </div>
        </>
      )}
      {tab === "twin" && <DigitalTwinPanel isDarkMode={isDarkMode} />}
    </div>
  );
}

function TopHeader({ isDarkMode, setIsDarkMode, onOpenEditor, onOpenHeightmap }) {
  const fault   = useStore((s) => s.telemetry.fault);
  const alerts  = useStore((s) => s.alerts);
  const simMode = useStore((s) => s.simMode);
  return (
    <header className="flex justify-between items-center mb-2">
      <h1 className="text-3xl font-bold tracking-widest text-blue-500 drop-shadow-sm">INDUS<span className={isDarkMode ? "text-gray-100" : "text-gray-900"}>3D</span></h1>
      <div className="flex gap-3 items-center">
        {alerts.length > 0 && <div className="flex items-center gap-1 px-3 py-1.5 bg-red-600 text-white rounded-full text-xs font-bold animate-pulse"><Bell size={13} />{alerts.length} Alert{alerts.length > 1 ? "s" : ""}</div>}
        <button onClick={onOpenHeightmap} className={`flex items-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-widest rounded-full border transition-colors ${isDarkMode ? "bg-gray-800 border-gray-700 text-emerald-400 hover:bg-gray-700" : "bg-white border-gray-300 text-emerald-600 shadow-sm hover:bg-gray-50"}`}><Map size={16} />Heightmap</button>
        <button onClick={onOpenEditor} className={`flex items-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-widest rounded-full border transition-colors ${isDarkMode ? "bg-gray-800 border-gray-700 text-blue-400 hover:bg-gray-700" : "bg-white border-gray-300 text-blue-600 shadow-sm hover:bg-gray-50"}`}><FileText size={16} />Config</button>
        <button onClick={() => setIsDarkMode(!isDarkMode)} className={`p-2 rounded-full border transition-colors ${isDarkMode ? "bg-gray-800 border-gray-700 text-yellow-400" : "bg-white border-gray-300 text-indigo-600 shadow-sm"}`}>{isDarkMode ? <Sun size={18} /> : <Moon size={18} />}</button>
        <div className={`flex items-center gap-3 px-4 py-2 rounded-full border ${isDarkMode ? "bg-gray-900 border-gray-800" : "bg-white border-gray-300 shadow-sm"}`}>
          <div className={`w-3 h-3 rounded-full animate-pulse ${fault ? "bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.7)]" : "bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.7)]"}`} />
          <span className={`text-xs uppercase tracking-widest font-semibold ${isDarkMode ? "text-gray-400" : "text-gray-600"}`}>
            {simMode ? "SIM MODE" : fault ? "SYSTEM FAULT" : "Live Connection"}
          </span>
        </div>
      </div>
    </header>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ROOT APP
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [isDarkMode, setIsDarkMode]       = useState(true);
  const [showEditor, setShowEditor]       = useState(false);
  const [showHeightmap, setShowHeightmap] = useState(false);

  const initWebSocket   = useStore((s) => s.initWebSocket);
  const fetchProfile    = useStore((s) => s.fetchProfile);
  const fetchSensorData = useStore((s) => s.fetchSensorData);
  const fetchActionLog  = useStore((s) => s.fetchActionLog);
  const bed             = useStore((s) => s.bed);

  useEffect(() => {
    fetchProfile();
    initWebSocket();
    fetchSensorData();
    fetchActionLog();
    const iv = setInterval(fetchSensorData, 2000);
    return () => clearInterval(iv);
  }, [fetchProfile, initWebSocket, fetchSensorData, fetchActionLog]);

  const bx = (bed.size_x_mm ?? 300) / 10;
  const by = (bed.size_y_mm ?? 300) / 10;
  const ox = bed.origin_center ? 0 : bx / 2;
  const oz = bed.origin_center ? 0 : by / 2;

  return (
    <div className={`flex h-screen w-full font-sans overflow-hidden transition-colors duration-300 ${isDarkMode ? "bg-gray-950 text-gray-100" : "bg-gray-100 text-gray-900"}`}>
      <div className="flex-1 relative flex flex-col p-6">
        <TopHeader isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode}
          onOpenEditor={() => setShowEditor(true)} onOpenHeightmap={() => setShowHeightmap(true)} />
        <ProfileBar isDarkMode={isDarkMode} />
        <AlertBar isDarkMode={isDarkMode} />
        {showEditor    && <ConfigEditor   isDarkMode={isDarkMode} onClose={() => setShowEditor(false)} />}
        {showHeightmap && <HeightmapModal isDarkMode={isDarkMode} onClose={() => setShowHeightmap(false)} />}
        <div className={`flex-1 rounded-2xl flex flex-col items-center justify-center relative overflow-hidden border ${isDarkMode ? "bg-gray-900 border-gray-800 shadow-inner" : "bg-gray-200 border-gray-300 shadow-inner"}`}>
          <Canvas camera={{ position: [ox, ox * 1.2 + 8, oz + 18], fov: 50 }}>
            <ambientLight intensity={isDarkMode ? 0.3 : 0.8} />
            <directionalLight position={[10, 20, 10]} intensity={1.5} />
            <pointLight position={[ox, 10, oz]} intensity={0.5} />
            <Environment preset="city" />
            <PrintBed />
            <Toolhead />
            <GCodeVisualizer />
            <OrbitControls target={[ox, 0, oz]} maxPolarAngle={Math.PI / 2 - 0.05}
              makeDefault enableDamping dampingFactor={0.2}
              rotateSpeed={1.8} zoomSpeed={1.5} panSpeed={1.2} />
            <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
              <GizmoViewcube color="white" strokeColor="gray" textColor="black" hoverColor="#60a5fa" opacity={0.8} />
            </GizmoHelper>
          </Canvas>
        </div>
      </div>
      <Sidebar isDarkMode={isDarkMode} />
    </div>
  );
}
