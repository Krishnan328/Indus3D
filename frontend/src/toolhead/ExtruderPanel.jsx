import React, { useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { useStore } from "../store";
import { feedrateFromSpeed, reasonDisabled, toolMacroButtons } from "../slices/toolheadLogic";

// Extrude / retract with amount and speed presets (Settings -> Control), the load / unload / clean / park
// macros the printer actually has, and a clear reason when the extruder is cold or a print is running.
export function ExtruderPanel({ btn, printing, status, capabilities, connected }) {
  const extrude = useStore((s) => s.extrude);
  const runMacro = useStore((s) => s.runMacro);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const amounts = uiPrefs.extrudeAmounts?.length ? uiPrefs.extrudeAmounts : [5, 10, 25, 50];
  const speeds = uiPrefs.extrudeSpeeds?.length ? uiPrefs.extrudeSpeeds : [2, 5, 10];
  const [amount, setAmount] = useState(amounts[1] ?? amounts[0]);
  const [speed, setSpeed] = useState(speeds[1] ?? speeds[0]);
  const reason = reasonDisabled("extrude", { printing, capabilities, status, connected });
  const macros = toolMacroButtons(capabilities);
  const chip = (active) => `${btn} px-2 text-[10px] ${active ? "bg-blue-600 text-white" : ""}`;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1"><span className="w-12 text-[9px] uppercase opacity-60">Amount</span>
        {amounts.map((a) => <button key={a} className={chip(amount === a)} onClick={() => setAmount(a)}>{a} mm</button>)}</div>
      <div className="flex flex-wrap items-center gap-1"><span className="w-12 text-[9px] uppercase opacity-60">Speed</span>
        {speeds.map((v) => <button key={v} className={chip(speed === v)} onClick={() => setSpeed(v)}>{v} mm/s</button>)}</div>
      <div className="grid grid-cols-2 gap-1.5" title={reason || undefined}>
        <button className={`${btn} gap-1 text-[11px]`} disabled={!!reason} onClick={() => extrude(-amount, feedrateFromSpeed(speed))}><ArrowUpFromLine size={14} />Retract</button>
        <button className={`${btn} gap-1 text-[11px]`} disabled={!!reason} onClick={() => extrude(amount, feedrateFromSpeed(speed))}><ArrowDownToLine size={14} />Extrude</button>
      </div>
      {reason && <div className="text-[9px] opacity-60 text-center">{reason}</div>}
      {macros.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {macros.map(({ key, label, macro }) => (
            <button key={key} className={`${btn} px-2 text-[10px] flex-1`} onClick={() => runMacro(macro)} title={`Runs macro ${macro}`}>{label}</button>
          ))}
        </div>
      )}
    </div>
  );
}
