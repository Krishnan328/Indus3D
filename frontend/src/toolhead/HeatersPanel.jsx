import React, { useState } from "react";
import { useStore } from "../store";
import { ToolheadSlider } from "./ToolheadSlider";
import { controllableFans, fromPercent, heaterCeiling, parseSetpoint, shortName, toPercent } from "../slices/toolheadLogic";

// Heater setpoints (bounded by the configured max_temp), fan and output-pin sliders.
function HeaterRow({ name, status, limits, t }) {
  const setHeaterTarget = useStore((s) => s.setHeaterTarget);
  const [text, setText] = useState("");
  const live = status[name] || {};
  const ceiling = heaterCeiling(limits, name);
  const commit = () => {
    const value = parseSetpoint(text, ceiling);
    if (value == null) return;
    setHeaterTarget(name, value);
    setText("");
  };
  return (
    <div className={`px-2 py-1.5 flex items-center gap-2 ${t.cell}`}>
      <div className="min-w-[4.5rem]">
        <div className="text-[9px] uppercase tracking-widest opacity-60">{name === "heater_bed" ? "Bed" : shortName(name)}</div>
        <div className="font-mono text-sm font-bold">{Number.isFinite(live.temperature) ? live.temperature.toFixed(1) : "—"}°
          <span className="text-[9px] font-normal opacity-60"> / {live.target ? `${live.target.toFixed(0)}°` : "off"}</span></div>
      </div>
      <input type="number" inputMode="decimal" min="0" max={ceiling ?? undefined} step="1" value={text} placeholder={live.target ? String(Math.round(live.target)) : "°C"}
        aria-label={`${name} target`} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && commit()}
        title={ceiling != null ? `max ${ceiling}°C (configured max_temp minus a safety margin)` : "configured max unknown"}
        className="w-16 px-1.5 py-1 text-xs font-mono bg-transparent border border-current/20 rounded outline-none" />
      <button className="px-2 py-1 text-[10px] font-bold rounded bg-orange-600 text-white disabled:opacity-40" disabled={parseSetpoint(text, ceiling) == null} onClick={commit}>Set</button>
      <button className="px-2 py-1 text-[10px] font-bold rounded border border-current/30" disabled={!live.target} onClick={() => setHeaterTarget(name, 0)}>Off</button>
      <div className="ml-auto text-[9px] font-mono opacity-60" title="heater power">{Number.isFinite(live.power) ? `${Math.round(live.power * 100)}%` : ""}</div>
    </div>
  );
}

export function HeatersPanel({ status, capabilities, limits, t }) {
  const setFanSpeed = useStore((s) => s.setFanSpeed);
  const setOutputPin = useStore((s) => s.setOutputPin);
  const heaters = capabilities.heaters || [];
  const fans = controllableFans(capabilities);
  const pins = capabilities.outputs || [];
  return (
    <div className="flex flex-col gap-2">
      {heaters.map((h) => <HeaterRow key={h} name={h} status={status} limits={limits} t={t} />)}
      {!heaters.length && <div className="text-[10px] opacity-60">No heaters reported by Klipper.</div>}
      {fans.length > 0 && <div className="grid gap-2 pt-1">
        {fans.map((f) => (
          <ToolheadSlider key={f} label={f === "fan" ? "Part fan" : shortName(f)} min={0} max={100} step={1}
            value={toPercent(status[f]?.speed)} format={(v) => `${v}%`} accent="accent-cyan-500"
            onCommit={(v) => setFanSpeed(f, fromPercent(v))} />
        ))}
      </div>}
      {pins.length > 0 && <div className="grid gap-2 pt-1">
        {pins.map((p) => (
          <ToolheadSlider key={p} label={shortName(p)} min={0} max={100} step={1} value={toPercent(status[p]?.value)}
            format={(v) => `${v}%`} accent="accent-violet-500" onCommit={(v) => setOutputPin(p, fromPercent(v))} />
        ))}
      </div>}
    </div>
  );
}
