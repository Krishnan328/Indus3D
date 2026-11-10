import React from "react";
import { ChevronUp, ChevronDown, Save } from "lucide-react";
import { useStore } from "../store";
import { cleanIncrements, formatStep, reasonDisabled, zOffsetOf } from "../slices/toolheadLogic";

// Live Z babystep (SET_GCODE_OFFSET Z_ADJUST=.. MOVE=1) with the user's increments, and saving the result.
export function ZOffsetPanel({ btn, status, capabilities, connected }) {
  const babystepZ = useStore((s) => s.babystepZ);
  const saveZOffset = useStore((s) => s.saveZOffset);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const steps = cleanIncrements(uiPrefs.zOffsetSteps, [0.01, 0.025, 0.05, 0.1]);
  const offset = zOffsetOf(status);
  const noProbe = reasonDisabled("save_probe", { capabilities, connected });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[9px] uppercase tracking-widest opacity-60">Current Z offset</span>
        <span className="font-mono text-sm font-bold" data-testid="z-offset">{offset == null ? "—" : `${offset.toFixed(3)} mm`}</span>
      </div>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s) => <button key={`u${s}`} className={`${btn} text-[10px] gap-0.5`} disabled={!connected} onClick={() => babystepZ(s)} title="Raise the nozzle (more distance from the bed)"><ChevronUp size={12} />{formatStep(s)}</button>)}
        {steps.map((s) => <button key={`d${s}`} className={`${btn} text-[10px] gap-0.5`} disabled={!connected} onClick={() => babystepZ(-s)} title="Lower the nozzle (closer to the bed)"><ChevronDown size={12} />{formatStep(-s)}</button>)}
      </div>
      <div className="grid grid-cols-2 gap-1.5 pt-1">
        <button className={`${btn} text-[10px] gap-1`} disabled={!connected || !!noProbe} title={noProbe || "Z_OFFSET_APPLY_PROBE"} onClick={() => saveZOffset("probe")}><Save size={12} />Save to probe</button>
        <button className={`${btn} text-[10px] gap-1`} disabled={!connected} title="Z_OFFSET_APPLY_ENDSTOP" onClick={() => saveZOffset("endstop")}><Save size={12} />Save to endstop</button>
      </div>
      <p className="text-[9px] opacity-50">Saving stages the value in Klipper; run SAVE_CONFIG (restarts the printer) to keep it. Babystepping is allowed during a print.</p>
    </div>
  );
}
