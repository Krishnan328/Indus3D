import React, { useState } from "react";
import {
  Crosshair, Home, ArrowUp, ArrowDown, ArrowLeft, ArrowRight,
  ChevronsUp, ChevronsDown, Unlock, AlertTriangle, Flame, ShieldAlert, ChevronDown, ChevronUp, RefreshCw
} from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

export function ToolheadControls() {
  const tState = useStore((s) => s.telemetry?.state);
  const x = useStore((s) => (s.telemetry?.live_x !== undefined ? s.telemetry.live_x : s.telemetry?.x)) || 0;
  const y = useStore((s) => (s.telemetry?.live_y !== undefined ? s.telemetry.live_y : s.telemetry?.y)) || 0;
  const z = useStore((s) => (s.telemetry?.live_z !== undefined ? s.telemetry.live_z : s.telemetry?.z)) || 0;
  const extTemp = useStore((s) => s.telemetry?.extTemp ?? 0);
  const homedAxes = useStore((s) => s.telemetry?.homed_axes) ?? "";
  const isHomed = useStore((s) => s.telemetry?.is_homed) ?? ["x", "y", "z"].every(a => homedAxes.includes(a));

  const homeAxes = useStore((s) => s.homeAxes);
  const homeAxis = useStore((s) => s.homeAxis);
  const motorsOff = useStore((s) => s.motorsOff);
  const jogToolhead = useStore((s) => s.jogToolhead);
  const moveToolhead = useStore((s) => s.moveToolhead);
  const extrudeFilament = useStore((s) => s.extrudeFilament);
  const endstopsState = useStore((s) => s.endstopsState);
  const queryEndstops = useStore((s) => s.queryEndstops);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const [showEndstops, setShowEndstops] = useState(false);
  const [queryingEndstops, setQueryingEndstops] = useState(false);

  const moveDistances = (uiPrefs.moveDistances?.length ? uiPrefs.moveDistances : [0.05, 0.1, 1, 10, 50, 100])
    .map(v => parseFloat(v))
    .filter(v => Number.isFinite(v) && v > 0);
  const activeDistances = moveDistances.length ? moveDistances : [0.05, 0.1, 1, 10, 50, 100];
  const [step, setStep] = useState(activeDistances[Math.floor(activeDistances.length / 2)] ?? 10);

  const [extrudeStep, setExtrudeStep] = useState(10);
  const [targetX, setTargetX] = useState("");
  const [targetY, setTargetY] = useState("");
  const [targetZ, setTargetZ] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const isPrinting = ["printing", "paused"].includes(tState);
  const disabled = busy || isPrinting;
  const isCold = extTemp < 170;

  const run = async (action) => {
    setBusy(true); setMessage("");
    const result = await action();
    setMessage(result?.error || result?.detail || (result?.simulated ? "Queued in simulator" : "Command sent"));
    setBusy(false);
  };

  const handleQueryEndstops = async () => {
    setQueryingEndstops(true);
    await queryEndstops();
    setQueryingEndstops(false);
  };

  const getEndstopStatus = (axis) => {
    if (!endstopsState) return null;
    const key = axis.toLowerCase();
    const raw = endstopsState[key] ??
                endstopsState[`stepper_${key}`] ??
                endstopsState[axis] ??
                (key === "probe" ? (endstopsState.probe ?? endstopsState.bltouch ?? endstopsState["z:virtual_endstop"]) : null);
    if (!raw) return null;
    return String(raw).toLowerCase();
  };

  const handleAbsoluteMove = () => {
    const coords = {};
    if (targetX.trim() !== "") {
      const val = parseFloat(targetX);
      if (Number.isFinite(val)) coords.x = val;
    }
    if (targetY.trim() !== "") {
      const val = parseFloat(targetY);
      if (Number.isFinite(val)) coords.y = val;
    }
    if (targetZ.trim() !== "") {
      const val = parseFloat(targetZ);
      if (Number.isFinite(val)) coords.z = val;
    }
    if (!Object.keys(coords).length) return;
    const xySpeed = Number(uiPrefs?.toolheadSpeedXY) > 0 ? Number(uiPrefs.toolheadSpeedXY) : 50;
    const zSpeed = Number(uiPrefs?.toolheadSpeedZ) > 0 ? Number(uiPrefs.toolheadSpeedZ) : 10;
    const speed = (coords.x === undefined && coords.y === undefined && coords.z !== undefined) ? zSpeed : xySpeed;
    const feedrate = speed * 60;
    return run(async () => {
      const res = await moveToolhead(coords, feedrate);
      if (!res?.error) {
        setTargetX("");
        setTargetY("");
        setTargetZ("");
      }
      return res;
    });
  };

  const jog = (axis, amount) => {
    const val = parseFloat(amount);
    if (!Number.isFinite(val) || val === 0) return;
    const inverted = axis === "x" ? !!uiPrefs?.invertX : axis === "y" ? !!uiPrefs?.invertY : !!uiPrefs?.invertZ;
    const xySpeed = Number(uiPrefs?.toolheadSpeedXY) > 0 ? Number(uiPrefs.toolheadSpeedXY) : 50;
    const zSpeed = Number(uiPrefs?.toolheadSpeedZ) > 0 ? Number(uiPrefs.toolheadSpeedZ) : 10;
    const feedrate = (axis === "z" ? zSpeed : xySpeed) * 60;
    return run(() => jogToolhead({ [axis]: inverted ? -val : val }, feedrate));
  };

  const handleExtrude = (amount) => {
    if (isCold) {
      setMessage("⚠️ Extrusion blocked: Nozzle below 170°C min_extrude_temp");
      return;
    }
    return run(() => extrudeFilament(amount, 300));
  };

  const btn = `flex items-center justify-center h-9 ${t.cell} hover:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed`;

  return (
    <section className={`h-full min-h-[300px] p-4 flex flex-col justify-between ${t.panel}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="flex items-center gap-2 text-blue-400">
          <Crosshair size={16} />
          <h3 className={t.heading}>Toolhead & Motion</h3>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-[10px]">
          <span className="opacity-75">X {Number(x).toFixed(1)} · Y {Number(y).toFixed(1)} · Z {Number(z).toFixed(2)}</span>
          <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
            isHomed ? "text-emerald-400 bg-emerald-950/60 border border-emerald-800/50" :
            homedAxes ? "text-amber-400 bg-amber-950/60 border border-amber-800/50" :
            "text-zinc-400 bg-zinc-800/60 border border-zinc-700/50"
          }`}>
            {isHomed ? "HOMED" : homedAxes ? homedAxes.toUpperCase() : "UNHOMED"}
          </span>
        </div>
      </div>

      {/* Unhomed Warning if not homed */}
      {!isHomed && !isPrinting && (
        <div className="mb-2 px-2.5 py-1.5 rounded bg-amber-950/40 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between shrink-0">
          <div className="flex items-center gap-1.5">
            <AlertTriangle size={13} className="text-amber-400 shrink-0" />
            <span className="text-[10px]">Printer unhomed. Home axes before jogging.</span>
          </div>
          <button
            onClick={() => run(homeAxes)}
            disabled={disabled}
            className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-500 text-white"
          >
            Home All
          </button>
        </div>
      )}

      {/* Distance Selector & Homing Bar */}
      <div className="flex flex-wrap items-center gap-1.5 mb-2.5 shrink-0">
        <div className="flex flex-1 items-center gap-1 overflow-x-auto">
          {activeDistances.map((value) => (
            <button
              key={value}
              onClick={() => setStep(value)}
              disabled={disabled}
              className={`flex-1 min-w-[36px] py-1 text-[10px] font-bold ${t.chip} ${
                step === value ? "bg-blue-600 text-white" : t.cell
              }`}
            >
              {value}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => run(homeAxes)}
            disabled={disabled}
            className={`px-2 py-1 text-[10px] font-bold rounded ${
              brutalist
                ? "bg-[#32E0C4] text-[#111] border-2 border-[#111]"
                : "bg-emerald-700 hover:bg-emerald-600 text-white"
            } disabled:opacity-40`}
            title="Home All Axes (G28)"
          >
            <Home size={12} className="inline mr-1" /> All
          </button>
          <button
            onClick={() => run(() => homeAxis("x"))}
            disabled={disabled}
            className={`px-1.5 py-1 text-[10px] font-mono font-bold rounded ${t.cell} hover:border-blue-400 disabled:opacity-40`}
            title="Home X Axis (G28 X)"
          >
            X
          </button>
          <button
            onClick={() => run(() => homeAxis("y"))}
            disabled={disabled}
            className={`px-1.5 py-1 text-[10px] font-mono font-bold rounded ${t.cell} hover:border-blue-400 disabled:opacity-40`}
            title="Home Y Axis (G28 Y)"
          >
            Y
          </button>
          <button
            onClick={() => run(() => homeAxis("z"))}
            disabled={disabled}
            className={`px-1.5 py-1 text-[10px] font-mono font-bold rounded ${t.cell} hover:border-blue-400 disabled:opacity-40`}
            title="Home Z Axis (G28 Z)"
          >
            Z
          </button>
          <button
            onClick={() => run(motorsOff)}
            disabled={disabled}
            className={`px-2 py-1 text-[10px] font-bold rounded ${
              brutalist
                ? "bg-gray-200 text-[#111] border-2 border-[#111]"
                : "bg-white/10 hover:bg-white/20 text-gray-300 border border-white/10"
            } disabled:opacity-40`}
            title="Release motor holding torque (M84 Motors Off)"
          >
            <Unlock size={11} className="inline mr-1" /> Motors Off
          </button>
          <button
            onClick={() => {
              const next = !showEndstops;
              setShowEndstops(next);
              if (next && !endstopsState) handleQueryEndstops();
            }}
            className={`px-2 py-1 text-[10px] font-bold rounded flex items-center gap-1 ${
              brutalist
                ? "bg-purple-200 text-[#111] border-2 border-[#111]"
                : "bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 border border-purple-500/30"
            }`}
            title="Inspect Endstops Status"
          >
            <ShieldAlert size={11} /> Endstops {showEndstops ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          </button>
        </div>
      </div>

      {/* Endstops Section / Accordion */}
      {showEndstops && (
        <div className={`mb-2.5 p-2.5 rounded-lg border ${
          brutalist ? "border-2 border-[#111] bg-white text-[#111]" : `${t.border} bg-black/20`
        } flex flex-col gap-2 shrink-0 animate-in fade-in duration-150`}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-wider opacity-70">Endstops State</span>
            <button
              type="button"
              onClick={handleQueryEndstops}
              disabled={queryingEndstops}
              className={`px-2 py-0.5 text-[9px] font-bold rounded flex items-center gap-1 transition-colors ${
                brutalist
                  ? "border border-[#111] bg-[#FFE9A8] text-[#111]"
                  : "bg-blue-600/30 hover:bg-blue-600/50 text-blue-300 border border-blue-500/30"
              }`}
            >
              <RefreshCw size={10} className={queryingEndstops ? "animate-spin" : ""} />
              <span>{queryingEndstops ? "Querying..." : "Check Endstops"}</span>
            </button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
            {["X", "Y", "Z", "Probe"].map((axis) => {
              const status = getEndstopStatus(axis);
              const isTriggered = status === "triggered";
              const isOpen = status === "open";
              return (
                <div key={axis} className={`flex items-center justify-between px-2 py-1 rounded ${t.cell} text-[10px] font-mono`}>
                  <span className="font-bold opacity-75">{axis}:</span>
                  {status ? (
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${
                      isTriggered
                        ? "bg-red-500/20 text-red-400 border border-red-500/40"
                        : isOpen
                          ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                          : "bg-gray-500/20 text-gray-400"
                    }`}>
                      {isTriggered ? "TRIGGERED" : isOpen ? "OPEN" : status.toUpperCase()}
                    </span>
                  ) : (
                    <span className="opacity-40 text-[9px]">Unknown</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Motion Controls Grid */}
      <div className="grid grid-cols-[1fr_1fr] gap-3 flex-1 items-center my-1">
        {/* XY Jog Wheel */}
        <div className="grid grid-cols-3 gap-1 place-items-stretch">
          <span />
          <button className={btn} disabled={disabled} onClick={() => jog("y", step)} title="Y+">
            <ArrowUp size={15} />
          </button>
          <span />
          <button className={btn} disabled={disabled} onClick={() => jog("x", -step)} title="X-">
            <ArrowLeft size={15} />
          </button>
          <div className={`flex items-center justify-center text-[9px] font-bold opacity-60 ${t.cell}`}>
            XY
          </div>
          <button className={btn} disabled={disabled} onClick={() => jog("x", step)} title="X+">
            <ArrowRight size={15} />
          </button>
          <span />
          <button className={btn} disabled={disabled} onClick={() => jog("y", -step)} title="Y-">
            <ArrowDown size={15} />
          </button>
          <span />
        </div>

        {/* Z Motion */}
        <div className="flex flex-col gap-1 justify-center h-full">
          <div className="grid grid-cols-2 gap-1">
            <button className={btn} disabled={disabled} onClick={() => jog("z", step)} title="Z+">
              <ChevronsUp size={16} />
              <span className="ml-1 text-[10px] font-bold">Z+</span>
            </button>
            <button className={btn} disabled={disabled} onClick={() => jog("z", -step)} title="Z-">
              <ChevronsDown size={16} />
              <span className="ml-1 text-[10px] font-bold">Z−</span>
            </button>
          </div>
          <span className="text-[9px] opacity-45 text-center mt-1">
            {isPrinting ? "Motion locked during print" : "Max 100 mm/jog"}
          </span>
        </div>
      </div>

      {/* Manual Extrusion & Retraction Section */}
      <div className={`mt-2 pt-2 border-t ${t.border} shrink-0`}>
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider opacity-60">Extruder</span>
            {isCold && (
              <span className="text-[9px] font-mono text-amber-400 flex items-center gap-1">
                <Flame size={10} /> Cold (&lt;170°C)
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {[1, 5, 10, 50].map((val) => (
              <button
                key={val}
                onClick={() => setExtrudeStep(val)}
                className={`px-1.5 py-0.5 text-[9px] font-mono font-bold rounded ${
                  extrudeStep === val ? "bg-orange-600 text-white" : t.cell
                }`}
              >
                {val}mm
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleExtrude(extrudeStep)}
            disabled={disabled || isCold}
            className={`flex-1 py-1 text-xs font-bold rounded flex items-center justify-center gap-1 transition-colors ${
              brutalist
                ? "bg-[#FF7700] text-white border-2 border-[#111]"
                : "bg-orange-600/80 hover:bg-orange-600 text-white disabled:opacity-40 disabled:cursor-not-allowed"
            }`}
            title={isCold ? "Heat nozzle to at least 170°C before extruding" : `Extrude ${extrudeStep} mm`}
          >
            <ArrowDown size={13} /> Extrude {extrudeStep}mm
          </button>
          <button
            onClick={() => handleExtrude(-extrudeStep)}
            disabled={disabled || isCold}
            className={`flex-1 py-1 text-xs font-bold rounded flex items-center justify-center gap-1 transition-colors ${
              brutalist
                ? "bg-gray-200 text-[#111] border-2 border-[#111]"
                : "bg-white/10 hover:bg-white/20 text-gray-200 border border-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
            }`}
            title={isCold ? "Heat nozzle to at least 170°C before retracting" : `Retract ${extrudeStep} mm`}
          >
            <ArrowUp size={13} /> Retract {extrudeStep}mm
          </button>
        </div>
      </div>

      {/* Target Absolute Position Inputs */}
      <div className={`mt-2 pt-2 border-t ${t.border} flex items-center gap-2 shrink-0`}>
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <span className="text-[10px] font-mono font-bold opacity-60">X</span>
          <input
            type="number"
            step="any"
            value={targetX}
            onChange={(e) => setTargetX(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAbsoluteMove()}
            placeholder={Number(x).toFixed(1)}
            disabled={disabled}
            className={`w-full min-w-0 px-2 py-1 text-xs font-mono outline-none rounded ${t.cell}`}
            title="Target X position (mm)"
          />
        </div>
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <span className="text-[10px] font-mono font-bold opacity-60">Y</span>
          <input
            type="number"
            step="any"
            value={targetY}
            onChange={(e) => setTargetY(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAbsoluteMove()}
            placeholder={Number(y).toFixed(1)}
            disabled={disabled}
            className={`w-full min-w-0 px-2 py-1 text-xs font-mono outline-none rounded ${t.cell}`}
            title="Target Y position (mm)"
          />
        </div>
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <span className="text-[10px] font-mono font-bold opacity-60">Z</span>
          <input
            type="number"
            step="any"
            value={targetZ}
            onChange={(e) => setTargetZ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAbsoluteMove()}
            placeholder={Number(z).toFixed(2)}
            disabled={disabled}
            className={`w-full min-w-0 px-2 py-1 text-xs font-mono outline-none rounded ${t.cell}`}
            title="Target Z position (mm)"
          />
        </div>
        <button
          onClick={handleAbsoluteMove}
          disabled={disabled || (targetX.trim() === "" && targetY.trim() === "" && targetZ.trim() === "")}
          className={`px-3 py-1 text-[10px] font-bold uppercase rounded ${
            brutalist
              ? "bg-[#4D90FE] text-white border-2 border-[#111]"
              : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 shrink-0"
          }`}
          title="Move toolhead to specified coordinates"
        >
          Move
        </button>
      </div>

      {message && <div className="mt-1 text-[10px] text-center font-mono opacity-80 shrink-0">{message}</div>}
    </section>
  );
}
