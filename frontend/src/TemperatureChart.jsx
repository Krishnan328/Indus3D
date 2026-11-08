import React, { useEffect, useState } from "react";
import { Thermometer, Flame, PowerOff, Check, Cpu } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

const SERIES = [
  { key: "extruder", label: "Extruder", colour: "#f97316" },
  { key: "bed", label: "Bed", colour: "#3b82f6" },
  { key: "chamber", label: "Chamber", colour: "#22c55e" },
];

const DEVICE_COLORS = [
  "#c084fc", // Purple (BTT Eddy in Mainsail)
  "#38bdf8", // Sky blue (BTT Eddy MCU in Mainsail)
  "#2dd4bf", // Teal (EBB36 in Mainsail)
  "#f472b6", // Pink
  "#fbbf24", // Amber
  "#a3e635", // Lime
];

function formatDeviceName(name) {
  if (!name) return "";
  if (name.toUpperCase() === name) return name;
  return name
    .split("_")
    .map((w) => {
      const lower = w.toLowerCase();
      if (lower === "mcu") return "MCU";
      if (lower === "btt") return "BTT";
      if (lower === "ebb") return "EBB";
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(" ");
}

const PRESETS = [
  { label: "Cooldown", ext: 0, bed: 0 },
  { label: "PLA", ext: 210, bed: 60 },
  { label: "PETG", ext: 240, bed: 75 },
  { label: "ABS", ext: 250, bed: 100 },
  { label: "TPU", ext: 220, bed: 50 },
];

function points(history, key, max) {
  if (history.length < 2) return "";
  return history.map((sample, index) => {
    const x = 8 + (index / (history.length - 1)) * 284;
    const y = 106 - (Math.max(0, Number(sample[key]) || 0) / max) * 94;
    return `${x.toFixed(1)},${Math.max(12, y).toFixed(1)}`;
  }).join(" ");
}

export function TemperatureChart() {
  const history = useStore((s) => s.temperatureHistory);
  const telemetry = useStore((s) => s.telemetry);
  const extTarget = useStore((s) => s.telemetry?.extTarget ?? s.telemetry?.ext_target ?? 0);
  const bedTarget = useStore((s) => s.telemetry?.bedTarget ?? s.telemetry?.bed_target ?? 0);
  const extTemp = useStore((s) => s.telemetry?.extTemp ?? s.telemetry?.ext_temp ?? 0);
  const bedTemp = useStore((s) => s.telemetry?.bedTemp ?? s.telemetry?.bed_temp ?? 0);
  const environment = useStore((s) => s.environment);
  const setTemperature = useStore((s) => s.setTemperature);
  const setPreheatPreset = useStore((s) => s.setPreheatPreset);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  // Local input state so live websocket frames don't stomp on user typing
  const [extInput, setExtInput] = useState("");
  const [extFocused, setExtFocused] = useState(false);
  const [bedInput, setBedInput] = useState("");
  const [bedFocused, setBedFocused] = useState(false);
  const [optimisticExtTarget, setOptimisticExtTarget] = useState(null);
  const [optimisticBedTarget, setOptimisticBedTarget] = useState(null);

  const effectiveExtTarget = optimisticExtTarget ?? extTarget;
  const effectiveBedTarget = optimisticBedTarget ?? bedTarget;

  // Clear optimistic override once live telemetry reflects target or after timeout
  useEffect(() => {
    if (optimisticExtTarget != null && Math.abs(extTarget - optimisticExtTarget) < 1) {
      setOptimisticExtTarget(null);
    }
  }, [extTarget, optimisticExtTarget]);

  useEffect(() => {
    if (optimisticBedTarget != null && Math.abs(bedTarget - optimisticBedTarget) < 1) {
      setOptimisticBedTarget(null);
    }
  }, [bedTarget, optimisticBedTarget]);

  // Dynamic Device Temperature Series (Mainsail Parity)
  const deviceTemps = telemetry?.device_temperatures || {};
  const devEntries = Object.entries(deviceTemps);

  const activeSeries = [
    ...SERIES,
    ...devEntries.map(([key, info], idx) => ({
      key,
      label: formatDeviceName(info.name || key),
      colour: DEVICE_COLORS[idx % DEVICE_COLORS.length],
      isDevice: true,
      current: info.temperature,
      target: info.target,
    })),
  ];

  const values = history.flatMap((sample) => activeSeries.map((series) => Number(sample[series.key]) || 0));
  const max = Math.max(50, Math.ceil(Math.max(...values, effectiveExtTarget || 0, effectiveBedTarget || 0) / 25) * 25);

  const isExtHeating = effectiveExtTarget > 0 && extTemp < effectiveExtTarget - 2;
  const isBedHeating = effectiveBedTarget > 0 && bedTemp < effectiveBedTarget - 2;

  const handleExtSubmit = (e) => {
    e?.preventDefault();
    const val = parseFloat(extInput);
    if (!isNaN(val)) {
      setOptimisticExtTarget(val);
      setTimeout(() => setOptimisticExtTarget(null), 4000);
      setTemperature("extruder", val);
    }
    setExtFocused(false);
  };

  const handleBedSubmit = (e) => {
    e?.preventDefault();
    const val = parseFloat(bedInput);
    if (!isNaN(val)) {
      setOptimisticBedTarget(val);
      setTimeout(() => setOptimisticBedTarget(null), 4000);
      setTemperature("bed", val);
    }
    setBedFocused(false);
  };

  const isExtFault = Number(extTemp) < 0 || Number(extTemp) > 350;
  const isBedFault = Number(bedTemp) < 0 || Number(bedTemp) > 150;
  const hasChamberSensor = environment.temperature != null && Number(environment.temperature) > 0;

  return (
    <section className={`h-full min-h-[280px] flex flex-col p-4 ${t.panel}`}>
      {/* Title Header */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2 text-orange-400">
          <Thermometer size={16} />
          <h3 className={t.heading}>Temperatures & Heating</h3>
        </div>
        <span className="text-[10px] opacity-50 font-mono">last 3 min</span>
      </div>

      {/* Heater Control Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-2.5 shrink-0">
        {/* Extruder Card */}
        <div className={`p-2.5 flex flex-col justify-between ${t.cell} ${isExtHeating ? "ring-1 ring-orange-500/50" : ""}`}>
          <div className="flex items-center justify-between">
            <span className={`${t.label} text-orange-400 font-semibold`}>Extruder / Nozzle</span>
            {isExtHeating && (
              <span className="flex items-center gap-1 text-[9px] font-bold text-orange-400 animate-pulse">
                <Flame size={11} /> Heating
              </span>
            )}
          </div>
          <div className="flex items-baseline justify-between my-1">
            <span className={`font-mono text-xl font-bold ${isExtFault ? "text-red-400 text-sm" : "text-orange-400"}`}>
              {isExtFault ? "--°C (Sensor Open)" : `${(Number(extTemp) || 0).toFixed(1)}°C`}
            </span>
            <span className="font-mono text-xs opacity-60">
              Target: <strong className={effectiveExtTarget > 0 ? "text-orange-400 font-bold" : "text-gray-400"}>{effectiveExtTarget > 0 ? `${effectiveExtTarget}°C` : "Off"}</strong>
            </span>
          </div>
          <form onSubmit={handleExtSubmit} className="flex items-center gap-1 mt-1">
            <input
              type="number"
              min="0"
              max="350"
              step="1"
              value={extFocused ? extInput : (effectiveExtTarget > 0 ? effectiveExtTarget : "")}
              placeholder="0°C"
              onFocus={() => {
                setExtFocused(true);
                setExtInput(effectiveExtTarget > 0 ? String(effectiveExtTarget) : "");
              }}
              onBlur={() => setTimeout(() => setExtFocused(false), 300)}
              onChange={(e) => setExtInput(e.target.value)}
              className={`w-full px-2 py-1 text-xs font-mono rounded ${
                brutalist
                  ? "border-2 border-[#111] bg-white text-[#111]"
                  : "bg-black/30 border border-white/10 text-white focus:border-orange-500 outline-none"
              }`}
            />
            <button
              type="submit"
              title="Set Extruder Temperature"
              className={`p-1.5 rounded transition-colors ${
                brutalist
                  ? "border-2 border-[#111] bg-[#FF7700] text-white hover:bg-black"
                  : "bg-orange-600 hover:bg-orange-500 text-white"
              }`}
            >
              <Check size={13} strokeWidth={2.5} />
            </button>
            <button
              type="button"
              onClick={() => {
                setOptimisticExtTarget(0);
                setTimeout(() => setOptimisticExtTarget(null), 4000);
                setTemperature("extruder", 0);
                setExtInput("");
                setExtFocused(false);
              }}
              title="Turn Extruder Off (0°C)"
              className={`p-1.5 rounded transition-colors ${
                brutalist
                  ? "border-2 border-[#111] bg-gray-200 hover:bg-gray-300 text-[#111]"
                  : "bg-white/10 hover:bg-white/20 text-gray-300"
              }`}
            >
              <PowerOff size={13} />
            </button>
          </form>
        </div>

        {/* Bed Card */}
        <div className={`p-2.5 flex flex-col justify-between ${t.cell} ${isBedHeating ? "ring-1 ring-blue-500/50" : ""}`}>
          <div className="flex items-center justify-between">
            <span className={`${t.label} text-blue-400 font-semibold`}>Heater Bed</span>
            {isBedHeating && (
              <span className="flex items-center gap-1 text-[9px] font-bold text-blue-400 animate-pulse">
                <Flame size={11} /> Heating
              </span>
            )}
          </div>
          <div className="flex items-baseline justify-between my-1">
            <span className={`font-mono text-xl font-bold ${isBedFault ? "text-red-400 text-sm" : "text-blue-400"}`}>
              {isBedFault ? "--°C (Sensor Open)" : `${(Number(bedTemp) || 0).toFixed(1)}°C`}
            </span>
            <span className="font-mono text-xs opacity-60">
              Target: <strong className={effectiveBedTarget > 0 ? "text-blue-400 font-bold" : "text-gray-400"}>{effectiveBedTarget > 0 ? `${effectiveBedTarget}°C` : "Off"}</strong>
            </span>
          </div>
          <form onSubmit={handleBedSubmit} className="flex items-center gap-1 mt-1">
            <input
              type="number"
              min="0"
              max="150"
              step="1"
              value={bedFocused ? bedInput : (effectiveBedTarget > 0 ? effectiveBedTarget : "")}
              placeholder="0°C"
              onFocus={() => {
                setBedFocused(true);
                setBedInput(effectiveBedTarget > 0 ? String(effectiveBedTarget) : "");
              }}
              onBlur={() => setTimeout(() => setBedFocused(false), 300)}
              onChange={(e) => setBedInput(e.target.value)}
              className={`w-full px-2 py-1 text-xs font-mono rounded ${
                brutalist
                  ? "border-2 border-[#111] bg-white text-[#111]"
                  : "bg-black/30 border border-white/10 text-white focus:border-blue-500 outline-none"
              }`}
            />
            <button
              type="submit"
              title="Set Bed Temperature"
              className={`p-1.5 rounded transition-colors ${
                brutalist
                  ? "border-2 border-[#111] bg-[#0088FF] text-white hover:bg-black"
                  : "bg-blue-600 hover:bg-blue-500 text-white"
              }`}
            >
              <Check size={13} strokeWidth={2.5} />
            </button>
            <button
              type="button"
              onClick={() => {
                setOptimisticBedTarget(0);
                setTimeout(() => setOptimisticBedTarget(null), 4000);
                setTemperature("bed", 0);
                setBedInput("");
                setBedFocused(false);
              }}
              title="Turn Bed Off (0°C)"
              className={`p-1.5 rounded transition-colors ${
                brutalist
                  ? "border-2 border-[#111] bg-gray-200 hover:bg-gray-300 text-[#111]"
                  : "bg-white/10 hover:bg-white/20 text-gray-300"
              }`}
            >
              <PowerOff size={13} />
            </button>
          </form>
        </div>

        {/* Chamber Card */}
        <div className={`p-2.5 flex flex-col justify-between ${t.cell}`}>
          <div className="flex items-center justify-between">
            <span className={`${t.label} text-green-400 font-semibold`}>Chamber</span>
            <span className="text-[9px] font-mono opacity-50">{hasChamberSensor ? "Passive" : "Passive (No Sensor)"}</span>
          </div>
          <div className="flex items-baseline justify-between my-1">
            <span className="font-mono text-xl font-bold text-green-400">
              {hasChamberSensor ? `${(Number(environment.temperature)).toFixed(1)}°C` : "--°C"}
            </span>
            <span className="font-mono text-xs opacity-60">{hasChamberSensor ? "ambient" : "unmonitored"}</span>
          </div>
          <div className="flex items-center justify-between text-[10px] font-mono opacity-60 mt-1 pt-1.5 border-t border-white/5">
            <span>Humidity</span>
            <span>{(Number(environment.humidity) || 0).toFixed(0)}%</span>
          </div>
        </div>
      </div>

      {/* Device Temperatures Strip (Mainsail Parity) */}
      {devEntries.length > 0 && (
        <div className="mb-2.5 shrink-0">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5 text-purple-400">
              <Cpu size={13} className="shrink-0" />
              <span className="text-[10px] uppercase font-bold tracking-wider opacity-70">
                Device Temperatures
              </span>
            </div>
            <span className="text-[9px] font-mono opacity-40">
              {devEntries.length} sensor{devEntries.length > 1 ? "s" : ""}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
            {devEntries.map(([key, info], idx) => {
              const color = DEVICE_COLORS[idx % DEVICE_COLORS.length];
              const displayName = formatDeviceName(info.name || key);
              const tempVal = Number(info.temperature);
              return (
                <div
                  key={key}
                  className={`p-2 rounded-lg flex items-center justify-between border transition-all ${
                    brutalist
                      ? "border-2 border-[#111] bg-white text-[#111] shadow-[2px_2px_0px_#111]"
                      : "bg-white/5 border-white/5 hover:border-white/10"
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0 pr-1">
                    <span
                      className="w-2 h-2 rounded-full shrink-0 shadow-sm"
                      style={{ background: color }}
                    />
                    <span className="text-[11px] font-semibold truncate font-mono" title={displayName}>
                      {displayName}
                    </span>
                  </div>
                  <div className="text-right shrink-0">
                    <span className="font-mono text-xs font-bold" style={{ color }}>
                      {!isNaN(tempVal) ? `${tempVal.toFixed(1)}°C` : "--"}
                    </span>
                    {info.target != null && info.target > 0 && (
                      <span className="text-[9px] font-mono opacity-50 block">
                        /{info.target}°C
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Preheat Quick Presets Bar */}
      <div className="flex items-center gap-1.5 mb-2.5 overflow-x-auto pb-1 shrink-0">
        <span className="text-[10px] uppercase font-bold tracking-wider opacity-60 mr-1 shrink-0">
          Presets:
        </span>
        {PRESETS.map((p) => {
          const isActive =
            p.ext === 0 && p.bed === 0
              ? extTarget === 0 && bedTarget === 0
              : extTarget === p.ext && bedTarget === p.bed;
          return (
            <button
              key={p.label}
              onClick={() => setPreheatPreset(p.ext, p.bed)}
              className={`px-2.5 py-1 text-[10px] font-mono font-bold rounded-lg transition-all shrink-0 ${
                brutalist
                  ? `border-2 border-[#111] ${isActive ? "bg-[#32E0C4] text-[#111]" : "bg-white text-[#111] hover:bg-gray-200"}`
                  : isActive
                  ? "bg-blue-600 text-white shadow-sm ring-1 ring-blue-400"
                  : "bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10"
              }`}
              title={p.ext === 0 ? "Turn off all heaters" : `Nozzle: ${p.ext}°C, Bed: ${p.bed}°C`}
            >
              {p.label} {p.ext > 0 ? `(${p.ext}/${p.bed})` : ""}
            </button>
          );
        })}
      </div>

      {/* SVG Temperature History Graph */}
      <div className="flex-1 min-h-0 relative">
        <svg viewBox="0 0 300 120" className="w-full h-full min-h-[110px]" role="img" aria-label="Temperature history chart">
          {[20, 45, 70, 95].map((y) => <line key={y} x1="8" x2="292" y1={y} y2={y} stroke="currentColor" opacity="0.12" strokeWidth="1" />)}
          {[70, 140, 210].map((x) => <line key={x} x1={x} x2={x} y1="12" y2="106" stroke="currentColor" opacity="0.08" strokeWidth="1" />)}
          {activeSeries.map((series) => (
            <polyline
              key={series.key}
              points={points(history, series.key, max)}
              fill="none"
              stroke={series.colour}
              strokeWidth={series.isDevice ? "1.8" : "2.2"}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={series.isDevice ? 0.9 : 1}
            />
          ))}
          <text x="9" y="11" className="fill-current opacity-45 text-[8px]">{max}°</text>
          <text x="9" y="118" className="fill-current opacity-45 text-[8px]">0°</text>
        </svg>
        {!history.length && <div className="absolute inset-0 flex items-center justify-center text-xs italic opacity-45">Collecting temperature history…</div>}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2.5 mt-1 text-[9px] uppercase tracking-widest opacity-75 shrink-0">
        {activeSeries.map((series) => (
          <span key={series.key} className="flex items-center gap-1">
            <i className="w-2 h-2 rounded-full shrink-0" style={{ background: series.colour }} />
            <span className="font-mono">{series.label}</span>
          </span>
        ))}
      </div>
    </section>
  );
}
