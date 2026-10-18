import React from "react";
import { Thermometer } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

const SERIES = [
  { key: "extruder", label: "Extruder", colour: "#f97316" },
  { key: "bed", label: "Bed", colour: "#3b82f6" },
  { key: "chamber", label: "Chamber", colour: "#22c55e" },
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
  const extTarget = useStore((s) => s.telemetry?.ext_target);
  const bedTarget = useStore((s) => s.telemetry?.bed_target);
  const extTemp = useStore((s) => s.telemetry?.extTemp);
  const bedTemp = useStore((s) => s.telemetry?.bedTemp);
  const environment = useStore((s) => s.environment);
  const t = useThemeTokens();
  const values = history.flatMap((sample) => SERIES.map((series) => Number(sample[series.key]) || 0));
  const max = Math.max(50, Math.ceil(Math.max(...values, extTarget || 0, bedTarget || 0) / 25) * 25);

  return (
    <section className={`h-full min-h-[250px] flex flex-col p-4 ${t.panel}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-orange-400"><Thermometer size={16} /><h3 className={t.heading}>Temperatures</h3></div>
        <span className="text-[10px] opacity-50 font-mono">last 3 min</span>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-3">
        {[
          ["Extruder", extTemp, extTarget, "text-orange-400"],
          ["Bed", bedTemp, bedTarget, "text-blue-400"],
          ["Chamber", environment.temperature, 0, "text-green-400"],
        ].map(([label, current, target, colour]) => (
          <div key={label} className={`px-2 py-1.5 ${t.cell}`}>
            <span className={t.label}>{label}</span>
            <div className={`font-mono text-base font-bold ${colour}`}>{(Number(current) || 0).toFixed(1)}°</div>
            <div className="font-mono text-[9px] opacity-50">{target ? `target ${target}°` : "ambient"}</div>
          </div>
        ))}
      </div>
      <div className="flex-1 min-h-0 relative">
        <svg viewBox="0 0 300 120" className="w-full h-full min-h-[120px]" role="img" aria-label="Temperature history chart">
          {[20, 45, 70, 95].map((y) => <line key={y} x1="8" x2="292" y1={y} y2={y} stroke="currentColor" opacity="0.12" strokeWidth="1" />)}
          {[70, 140, 210].map((x) => <line key={x} x1={x} x2={x} y1="12" y2="106" stroke="currentColor" opacity="0.08" strokeWidth="1" />)}
          {SERIES.map((series) => <polyline key={series.key} points={points(history, series.key, max)} fill="none" stroke={series.colour} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />)}
          <text x="9" y="11" className="fill-current opacity-45 text-[8px]">{max}°</text>
          <text x="9" y="118" className="fill-current opacity-45 text-[8px]">0°</text>
        </svg>
        {!history.length && <div className="absolute inset-0 flex items-center justify-center text-xs italic opacity-45">Collecting temperature history…</div>}
      </div>
      <div className="flex gap-3 mt-1 text-[9px] uppercase tracking-widest opacity-70">
        {SERIES.map((series) => <span key={series.key} className="flex items-center gap-1"><i className="w-2 h-2 rounded-full" style={{ background: series.colour }} />{series.label}</span>)}
      </div>
    </section>
  );
}
