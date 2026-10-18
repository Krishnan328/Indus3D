/**
 * QualityPanel.jsx
 * -----------------
 * Shows the live state of all 10 quality control parameters:
 *   1. Flow control
 *   2. Speed control
 *   3. Input shaper
 *   4. Pressure Advance, Temp, Fan, Z-Offset, Accel
 *   5. Velocity, SCV, Retraction, and Clog Pressure
 */

import React from "react";
import { TrendingUp, Gauge, Waves, Clock, Thermometer, Wind, Crosshair, Zap, MousePointer2, Activity, ShieldAlert, FastForward } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

const formatTs = (ts) =>
  new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString();

const BarGauge = ({ value, min, max, nominal, label, unit, invertColor = false }) => {
  const safeVal = value ?? nominal;
  const pct     = ((safeVal - min) / (max - min)) * 100;
  const nomPct  = ((nominal - min) / (max - min)) * 100;

  // Color calculation based on deviation from nominal
  const off     = Math.abs(safeVal - nominal);
  const range   = max - min;
  const offPct  = off / range;

  let color   = offPct < 0.1 ? "#22c55e"
              : offPct < 0.3 ? "#f59e0b"
              :                "#ef4444";

  if (invertColor) {
    color = offPct < 0.5 ? "#22c55e" : offPct < 0.8 ? "#f59e0b" : "#ef4444";
  }

  const track = "bg-gray-200 dark:bg-gray-800";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[10px] font-mono opacity-60">
        <span>{label}</span>
        <span className="font-bold" style={{ color }}>{typeof safeVal === 'number' ? safeVal.toFixed(safeVal % 1 !== 0 ? 2 : 0) : safeVal}{unit}</span>
      </div>
      <div className={`relative w-full h-2 rounded-full ${track}`}>
        {/* Nominal marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/40 rounded z-10"
          style={{ left: `${Math.max(0, Math.min(100, nomPct))}%` }}
        />
        {/* Fill */}
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }}
        />
      </div>
    </div>
  );
};

export function QualityPanel({ isDarkMode }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const quality = useStore((s) => s.quality);
  const toggleAutopilot = useStore((s) => s.toggleAutopilot);

  if (!quality) return null;

  const { active, corrections } = quality;
  const inner = t.panel;

  const typeIcon = {
    flow:         <TrendingUp size={11} className="text-yellow-400 shrink-0 mt-0.5" />,
    speed:        <Gauge      size={11} className="text-blue-400   shrink-0 mt-0.5" />,
    shaper:       <Waves      size={11} className="text-purple-400 shrink-0 mt-0.5" />,
    pa:           <MousePointer2 size={11} className="text-pink-400 shrink-0 mt-0.5" />,
    temp:         <Thermometer size={11} className="text-red-400 shrink-0 mt-0.5" />,
    fan:          <Wind size={11} className="text-cyan-400 shrink-0 mt-0.5" />,
    z_offset:     <Crosshair size={11} className="text-green-400 shrink-0 mt-0.5" />,
    velocity_scv: <Zap size={11} className="text-yellow-500 shrink-0 mt-0.5" />,
    velocity:     <FastForward size={11} className="text-orange-400 shrink-0 mt-0.5" />,
    scv:          <Activity size={11} className="text-indigo-400 shrink-0 mt-0.5" />,
    retraction:   <Waves size={11} className="text-indigo-400 shrink-0 mt-0.5" />,
    pressure:     <ShieldAlert size={11} className="text-red-500 shrink-0 mt-0.5" />
  };

  const typeLabel = {
    flow: "Flow M221", speed: "Speed M220", shaper: "Input Shaper",
    pa: "Pressure Adv", temp: "Hotend Temp", fan: "Part Fan",
    z_offset: "Z-Offset", velocity_scv: "Velocity/SCV/Accel",
    velocity: "Max Velocity", scv: "SCV (Jerk)", retraction: "Retraction",
    pressure: "Melt Pressure"
  };
  const typeUnit  = {
    flow: "%", speed: "%", shaper: " Hz", pa: "", temp: "°C",
    fan: "", z_offset: "mm", velocity_scv: "", velocity: " mm/s", scv: " mm/s",
    retraction: "mm", pressure: " u"
  };

  return (
    <div className={`h-full p-4 flex flex-col gap-4 ${inner}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-green-400">
          <TrendingUp size={16} />
          <h3 className={t.heading}>
            Quality Control
          </h3>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => toggleAutopilot(!active.enabled)}
            className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-widest transition-colors cursor-pointer
              ${brutalist ? "border-2 border-[#111]" : ""}
              ${active.enabled
                ? "bg-green-700 text-white hover:bg-green-600"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"}`}
          >
            {active.enabled ? "Autopilot ON" : "Autopilot OFF"}
          </button>
        </div>
      </div>

      {/* Live gauges */}
      <div className="flex flex-col gap-3 overflow-y-auto pr-1" style={{ maxHeight: '250px' }}>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          <BarGauge
            label="Flow (M221)"  unit="%"
            value={active.flow_pct}   min={85}  max={115} nominal={100}
          />
          <BarGauge
            label="Speed (M220)" unit="%"
            value={active.speed_pct}   min={50}  max={100} nominal={100}
          />
          <BarGauge
            label="Velocity Limit" unit=" mm/s"
            value={active.velocity}   min={50}  max={500} nominal={300}
          />
          <BarGauge
            label="Accel Limit" unit=" mm/s²"
            value={active.accel}   min={500}  max={5000} nominal={3000}
          />
          <BarGauge
            label="SCV (Jerk)" unit=" mm/s"
            value={active.scv}   min={1.0}  max={10.0} nominal={5.0}
          />
          <BarGauge
            label="Pressure Adv" unit=""
            value={active.pa}   min={0.0}  max={0.1} nominal={0.04}
          />
          <BarGauge
            label="Hotend Temp" unit="°C"
            value={active.temp}   min={190}  max={260} nominal={220}
          />
          <BarGauge
            label="Part Fan" unit=""
            value={active.fan}   min={0}  max={255} nominal={0}
          />
          <BarGauge
            label="Retraction" unit="mm"
            value={active.retraction}   min={0.0}  max={3.0} nominal={1.0}
          />
          <BarGauge
            label="Z-Offset" unit="mm"
            value={active.z_offset}   min={-0.1}  max={0.1} nominal={0.0}
          />
        </div>

        {/* Full width gauges at the bottom */}
        <BarGauge
          label="Melt Pressure (Clog Risk)" unit=" u"
          value={active.pressure}   min={0}  max={100} nominal={0}
          invertColor={true}
        />
        {active.shaper_hz > 0 && (
          <BarGauge
            label="Y Shaper Freq"        unit=" Hz"
            value={active.shaper_hz}     min={10}  max={80} nominal={active.shaper_hz}
          />
        )}
      </div>

      {/* Correction log */}
      {corrections && corrections.length > 0 && (
        <div className="flex flex-col gap-1 mt-auto border-t border-gray-700/50 pt-2">
          <span className="text-[9px] uppercase tracking-widest opacity-50">
            Recent corrections
          </span>
          <div className="flex flex-col gap-1 max-h-24 overflow-y-auto">
            {corrections.map((c, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 px-2 py-1.5 rounded text-[10px] font-mono
                  ${isDarkMode ? "bg-gray-900 border border-gray-800" : "bg-white border border-gray-200"}`}
              >
                {typeIcon[c.type] || <TrendingUp size={11} className="shrink-0 mt-0.5"/>}
                <div className="flex-1 min-w-0">
                  <div className={`font-bold ${isDarkMode ? "text-gray-200" : "text-gray-700"}`}>
                    {typeLabel[c.type] || c.type} → {typeof c.value === 'number' ? c.value.toFixed(2).replace(/\.00$/, '') : c.value}{typeUnit[c.type] || ""}
                  </div>
                  <div className="opacity-50 truncate">{c.reason}</div>
                </div>
                <div className="flex items-center gap-1 opacity-40 shrink-0">
                  <Clock size={8} />
                  {formatTs(c.ts)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {corrections && corrections.length === 0 && (
        <div className="text-[11px] opacity-40 italic text-center py-2 mt-auto">
          No corrections yet — toggle Autopilot ON and start print
        </div>
      )}
    </div>
  );
}
