/**
 * QualityPanel.jsx
 * -----------------
 * Shows the live state of the three quality control loops:
 *   1. Flow control  (M221)
 *   2. Speed control (M220)
 *   3. Input shaper  (SET_INPUT_SHAPER)
 *
 * And a scrollable log of every correction sent during the print.
 *
 * Drop into the Digital Twin tab in App.jsx:
 *   import { QualityPanel } from "./QualityPanel";
 *   <QualityPanel isDarkMode={isDarkMode} />   ← add above MaintenancePanel
 */

import React from "react";
import { TrendingUp, Gauge, Waves, Clock } from "lucide-react";
import { useStore } from "./store";

const formatTs = (ts) =>
  new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString();

const BarGauge = ({ value, min, max, nominal, label, unit, isDarkMode }) => {
  const pct     = ((value - min) / (max - min)) * 100;
  const nomPct  = ((nominal - min) / (max - min)) * 100;
  const off     = Math.abs(value - nominal);
  const color   = off < 3  ? "#22c55e"
                : off < 8  ? "#f59e0b"
                :             "#ef4444";

  const track = isDarkMode ? "bg-gray-800" : "bg-gray-200";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[10px] font-mono opacity-60">
        <span>{label}</span>
        <span className="font-bold" style={{ color }}>{value}{unit}</span>
      </div>
      <div className={`relative w-full h-2 rounded-full ${track}`}>
        {/* Nominal marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/40 rounded"
          style={{ left: `${nomPct}%` }}
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
  const quality = useStore((s) => s.quality);

  if (!quality) return null;

  const { active, corrections } = quality;
  const inner = isDarkMode ? "bg-gray-950 border-gray-800/80" : "bg-gray-50 border-gray-200";
  const cell  = isDarkMode ? "bg-gray-900 border-gray-800 text-gray-200" : "bg-white border-gray-200 text-gray-800";

  const typeIcon = {
    flow:    <TrendingUp size={11} className="text-yellow-400 shrink-0 mt-0.5" />,
    speed:   <Gauge      size={11} className="text-blue-400   shrink-0 mt-0.5" />,
    shaper:  <Waves      size={11} className="text-purple-400 shrink-0 mt-0.5" />,
  };

  const typeLabel = { flow: "Flow M221", speed: "Speed M220", shaper: "Input Shaper" };
  const typeUnit  = { flow: "%", speed: "%", shaper: " Hz" };

  return (
    <div className={`p-4 rounded-xl border flex flex-col gap-4 ${inner}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-green-400">
          <TrendingUp size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-sm">
            Quality Control
          </h3>
        </div>
        <span className={`text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-widest
          ${active.enabled
            ? "bg-green-700 text-white"
            : "bg-gray-700 text-gray-400"}`}>
          {active.enabled ? "active" : "idle"}
        </span>
      </div>

      {/* Live gauges */}
      <div className="flex flex-col gap-3">
        <BarGauge
          label="Flow rate (M221)"  unit="%"
          value={active.flow_pct}   min={85}  max={115} nominal={100}
          isDarkMode={isDarkMode}
        />
        <BarGauge
          label="Print speed (M220)" unit="%"
          value={active.speed_pct}   min={50}  max={100} nominal={100}
          isDarkMode={isDarkMode}
        />
        {active.shaper_hz > 0 && (
          <BarGauge
            label="Y shaper freq"        unit=" Hz"
            value={active.shaper_hz}     min={10}  max={80} nominal={active.shaper_hz}
            isDarkMode={isDarkMode}
          />
        )}
      </div>

      {/* Correction log */}
      {corrections && corrections.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-widest opacity-50">
            Recent corrections
          </span>
          <div className="flex flex-col gap-1 max-h-36 overflow-y-auto">
            {corrections.map((c, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 px-2 py-1.5 rounded text-[10px] font-mono
                  ${isDarkMode ? "bg-gray-900 border border-gray-800" : "bg-white border border-gray-200"}`}
              >
                {typeIcon[c.type] || <TrendingUp size={11} className="shrink-0 mt-0.5"/>}
                <div className="flex-1 min-w-0">
                  <div className={`font-bold ${isDarkMode ? "text-gray-200" : "text-gray-700"}`}>
                    {typeLabel[c.type] || c.type} → {c.value}{typeUnit[c.type] || ""}
                  </div>
                  <div className="opacity-50 truncate">{c.reason}</div>
                  <div className="flex items-center gap-1 opacity-40 mt-0.5">
                    <Clock size={8} />
                    {formatTs(c.ts)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {corrections && corrections.length === 0 && (
        <div className="text-[11px] opacity-40 italic text-center py-2">
          No corrections yet — print in progress will populate this
        </div>
      )}
    </div>
  );
}
