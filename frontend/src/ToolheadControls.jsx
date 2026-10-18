import React, { useState } from "react";
import { Crosshair, Home, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, ChevronsUp, ChevronsDown } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

export function ToolheadControls() {
  const tState = useStore((s) => s.telemetry?.state);
  const x = useStore((s) => s.telemetry?.x) || 0;
  const y = useStore((s) => s.telemetry?.y) || 0;
  const z = useStore((s) => s.telemetry?.z) || 0;
  const homeAxes = useStore((s) => s.homeAxes);
  const jogToolhead = useStore((s) => s.jogToolhead);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const t = useThemeTokens();
  const moveDistances = uiPrefs.moveDistances?.length ? uiPrefs.moveDistances : [0.05, 0.1, 1, 10];
  const [step, setStep] = useState(moveDistances[Math.floor(moveDistances.length / 2)] ?? 10);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const disabled = busy || ["printing", "paused"].includes(tState);

  const run = async (action) => {
    setBusy(true); setMessage("");
    const result = await action();
    setMessage(result.error || (result.simulated ? "Queued in simulator" : "Command sent"));
    setBusy(false);
  };
  // Invert-axis settings only flip the sign of the command sent from the UI —
  // they don't touch the printer's own configuration or physical direction.
  const jog = (axis, amount) => {
    const inverted = axis === "x" ? uiPrefs.invertX : axis === "y" ? uiPrefs.invertY : uiPrefs.invertZ;
    const feedrate = (axis === "z" ? uiPrefs.toolheadSpeedZ : uiPrefs.toolheadSpeedXY) * 60; // mm/s -> mm/min
    return run(() => jogToolhead({ [axis]: inverted ? -amount : amount }, feedrate));
  };
  const btn = `flex items-center justify-center h-9 ${t.cell} hover:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed`;

  return (
    <section className={`h-full min-h-[250px] p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center justify-between mb-3"><div className="flex items-center gap-2 text-blue-400"><Crosshair size={16} /><h3 className={t.heading}>Toolhead Control</h3></div><span className="font-mono text-[10px] opacity-60">X {x.toFixed(1)} · Y {y.toFixed(1)} · Z {z.toFixed(2)}</span></div>
      <div className="flex gap-1.5 mb-3">
        {moveDistances.map((value) => <button key={value} onClick={() => setStep(value)} disabled={disabled} className={`flex-1 py-1 text-[10px] font-bold ${t.chip} ${step === value ? "bg-blue-600 text-white" : t.cell}`}>{value} mm</button>)}
        <button onClick={() => run(homeAxes)} disabled={disabled} className={`px-3 text-[10px] font-bold ${t.chip} bg-emerald-700 text-white disabled:opacity-40`}><Home size={13} className="inline mr-1" />Home</button>
      </div>
      <div className="grid grid-cols-[1fr_1fr] gap-4 flex-1 items-center">
        <div className="grid grid-cols-3 gap-1 place-items-stretch">
          <span /><button className={btn} disabled={disabled} onClick={() => jog("y", step)}><ArrowUp size={15} /></button><span />
          <button className={btn} disabled={disabled} onClick={() => jog("x", -step)}><ArrowLeft size={15} /></button><div className={`flex items-center justify-center text-[9px] opacity-50 ${t.cell}`}>XY</div><button className={btn} disabled={disabled} onClick={() => jog("x", step)}><ArrowRight size={15} /></button>
          <span /><button className={btn} disabled={disabled} onClick={() => jog("y", -step)}><ArrowDown size={15} /></button><span />
        </div>
        <div className="grid grid-cols-2 gap-1 items-center">
          <button className={btn} disabled={disabled} onClick={() => jog("z", step)}><ChevronsUp size={16} /><span className="ml-1 text-[10px]">Z+</span></button>
          <button className={btn} disabled={disabled} onClick={() => jog("z", -step)}><ChevronsDown size={16} /><span className="ml-1 text-[10px]">Z−</span></button>
          <span className="col-span-2 text-[9px] opacity-45 text-center">Disabled during a print · max 25 mm/jog</span>
        </div>
      </div>
      {message && <div className="mt-2 text-[10px] text-center font-mono opacity-70">{message}</div>}
    </section>
  );
}
