import React, { useState } from "react";
import { useStore } from "../store";
import { ToolheadSlider } from "./ToolheadSlider";
import { FACTOR_RANGE, PA_RANGE, reasonDisabled } from "../slices/toolheadLogic";

// Speed / flow factors, pressure advance and firmware retraction. Safe to change during a print, and
// the quality controller yields these families after a manual change (see plugins/arbiter.py).
function NumberField({ label, value, onApply, min, max, step, unit, disabled }) {
  const [text, setText] = useState("");
  const apply = () => {
    const v = Number.parseFloat(text);
    if (Number.isFinite(v)) { onApply(Math.min(max, Math.max(min, v))); setText(""); }
  };
  return (
    <label className={`flex flex-col gap-0.5 text-[10px] ${disabled ? "opacity-40" : ""}`}>
      <span className="uppercase tracking-widest opacity-70">{label}</span>
      <input type="number" inputMode="decimal" min={min} max={max} step={step} value={text} disabled={disabled}
        placeholder={Number.isFinite(value) ? `${value}${unit || ""}` : "—"} onChange={(e) => setText(e.target.value)}
        onBlur={apply} onKeyDown={(e) => e.key === "Enter" && apply()}
        className="px-1.5 py-1 text-xs font-mono bg-transparent border border-current/20 rounded outline-none" />
    </label>
  );
}

export function TuningPanel({ status, capabilities, connected }) {
  const setSpeedFactor = useStore((s) => s.setSpeedFactor);
  const setFlowFactor = useStore((s) => s.setFlowFactor);
  const setPressureAdvance = useStore((s) => s.setPressureAdvance);
  const setRetraction = useStore((s) => s.setRetraction);
  const gm = status.gcode_move || {};
  const ext = status.extruder || {};
  const fr = status.firmware_retraction || {};
  const retractionReason = reasonDisabled("retraction", { capabilities, connected });
  return (
    <div className="flex flex-col gap-3">
      <ToolheadSlider label="Speed" min={FACTOR_RANGE[0]} max={FACTOR_RANGE[1]} step={5} value={Math.round((gm.speed_factor ?? 1) * 100)}
        format={(v) => `${v}%`} accent="accent-sky-500" onCommit={setSpeedFactor} disabled={!connected} />
      <ToolheadSlider label="Flow" min={FACTOR_RANGE[0]} max={FACTOR_RANGE[1]} step={1} value={Math.round((gm.extrude_factor ?? 1) * 100)}
        format={(v) => `${v}%`} accent="accent-emerald-500" onCommit={setFlowFactor} disabled={!connected} />
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Pressure advance" value={ext.pressure_advance} min={PA_RANGE[0]} max={PA_RANGE[1]} step={0.001} disabled={!connected}
          onApply={(v) => setPressureAdvance(v)} />
        <NumberField label="Smooth time (s)" value={ext.smooth_time} min={0} max={0.2} step={0.001} disabled={!connected}
          onApply={(v) => setPressureAdvance(ext.pressure_advance ?? 0, v)} />
      </div>
      <div className="pt-1 border-t border-current/10">
        <div className="text-[9px] uppercase tracking-widest opacity-60 mb-1">Firmware retraction</div>
        {retractionReason ? <div className="text-[10px] opacity-50">{retractionReason}</div> : (
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Retract (mm)" value={fr.retract_length} min={0} max={20} step={0.1} onApply={(v) => setRetraction({ retract_length: v })} />
            <NumberField label="Retract speed" value={fr.retract_speed} min={1} max={200} step={1} onApply={(v) => setRetraction({ retract_speed: v })} />
            <NumberField label="Extra on unretract" value={fr.unretract_extra_length} min={-5} max={5} step={0.05} onApply={(v) => setRetraction({ unretract_extra_length: v })} />
            <NumberField label="Unretract speed" value={fr.unretract_speed} min={1} max={200} step={1} onApply={(v) => setRetraction({ unretract_speed: v })} />
          </div>
        )}
      </div>
    </div>
  );
}
