import React, { useEffect, useState } from "react";
import { Crosshair, Home } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";
import { MovePanel } from "./toolhead/MovePanel";
import { ExtruderPanel } from "./toolhead/ExtruderPanel";
import { HeatersPanel } from "./toolhead/HeatersPanel";
import { TuningPanel } from "./toolhead/TuningPanel";
import { ZOffsetPanel } from "./toolhead/ZOffsetPanel";
import { LevelingPanel } from "./toolhead/LevelingPanel";
import { GoToPanel } from "./toolhead/GoToPanel";
import { isPrinting, reasonDisabled } from "./slices/toolheadLogic";

// Toolhead card: jog and home (bars / cross / circle), extruder, heaters + fans + outputs, speed / flow /
// pressure advance / retraction, Z babystep, leveling. Klipper status is polled only while this card is
// mounted. Everything the printer cannot do is hidden; things that make no sense during a print are
// disabled with the reason shown.
const TABS = [["move", "Move"], ["extruder", "Extruder"], ["heat", "Heat"], ["tune", "Tune"], ["z", "Z offset"], ["level", "Level"], ["goto", "Go to"]];

export function ToolheadControls() {
  const tState = useStore((s) => s.telemetry?.state);
  const x = useStore((s) => s.telemetry?.x) || 0;
  const y = useStore((s) => s.telemetry?.y) || 0;
  const z = useStore((s) => s.telemetry?.z) || 0;
  const homeSelected = useStore((s) => s.homeSelected);
  const jogToolhead = useStore((s) => s.jogToolhead);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const printerStatus = useStore((s) => s.printerStatus);
  const subscribePrinterStatus = useStore((s) => s.subscribePrinterStatus);
  const toolheadStatus = useStore((s) => s.toolheadStatus);
  const t = useThemeTokens();

  useEffect(() => subscribePrinterStatus(), [subscribePrinterStatus]);    // polls only while this card is mounted

  const moveDistances = uiPrefs.moveDistances?.length ? uiPrefs.moveDistances : [0.1, 1, 10, 50];
  const [tab, setTab] = useState("move");
  const [step, setStep] = useState(moveDistances[Math.floor(moveDistances.length / 2)] ?? 10);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const printing = isPrinting(tState);
  const connected = printerStatus.ok;
  const { status, capabilities, limits } = printerStatus;
  const moveReason = reasonDisabled("motion", { printing, connected: true });
  const disabled = busy || !!moveReason;
  const hideAxes = printing && uiPrefs.hideAxisControlsInPrint;

  const run = async (action) => {
    setBusy(true); setMessage("");
    const result = await action();
    setMessage(result.error || result.message || (result.simulated ? "Queued in simulator" : "Command sent"));
    setBusy(false);
  };
  // Invert-axis settings only flip the sign of the command sent from the UI —
  // they don't touch the printer's own configuration or physical direction.
  const jog = (axis, amount) => {
    const inverted = axis === "x" ? uiPrefs.invertX : axis === "y" ? uiPrefs.invertY : uiPrefs.invertZ;
    const feedrate = (axis === "z" ? uiPrefs.toolheadSpeedZ : uiPrefs.toolheadSpeedXY) * 60; // mm/s -> mm/min
    return run(() => jogToolhead({ [axis]: inverted ? -amount : amount }, feedrate));
  };
  const home = (axes) => run(() => homeSelected(axes));
  const btn = `flex items-center justify-center h-9 ${t.cell} hover:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed`;
  const panelProps = { btn, printing, status: status || {}, capabilities: capabilities || {}, connected, t };

  const homeButtons = uiPrefs.combinedXYHome
    ? [["XY", "XY"], ["Z", "Z"], ["", "All"]]
    : [["X", "X"], ["Y", "Y"], ["Z", "Z"], ["", "All"]];

  return (
    <section className={`h-full min-h-[250px] p-4 flex flex-col ${t.panel}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-blue-400"><Crosshair size={16} /><h3 className={t.heading}>Toolhead Control</h3></div>
        <span className="font-mono text-[10px] opacity-60">X {x.toFixed(1)} · Y {y.toFixed(1)} · Z {z.toFixed(2)}</span>
      </div>
      <div className="flex gap-1 mb-2 overflow-x-auto" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`px-2.5 py-1 text-[10px] font-bold whitespace-nowrap ${t.chip} ${tab === id ? "bg-blue-600 text-white" : t.cell}`}>{label}</button>
        ))}
      </div>
      {!connected && tab !== "move" && (
        <div className="mb-2 text-[10px] opacity-60" role="status">Klipper status unavailable{printerStatus.error ? `: ${printerStatus.error}` : ""}</div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto pr-0.5">
        {tab === "move" && (hideAxes
          ? <div className="text-[11px] opacity-60 text-center py-6">Axis controls are hidden during a print (Settings → Control).</div>
          : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-1.5">
                {moveDistances.map((value) => <button key={value} onClick={() => setStep(value)} disabled={disabled} className={`flex-1 min-w-[2.5rem] py-1 text-[10px] font-bold ${t.chip} ${step === value ? "bg-blue-600 text-white" : t.cell}`}>{value} mm</button>)}
              </div>
              <div className="flex gap-1.5 items-center">
                <Home size={13} className="opacity-60" />
                {homeButtons.map(([axes, label]) => (
                  <button key={label} onClick={() => home(axes)} disabled={disabled} title={moveReason || `Home ${axes || "all axes"}`}
                    className={`flex-1 py-1 text-[10px] font-bold ${t.chip} bg-emerald-700 text-white disabled:opacity-40`}>{label}</button>
                ))}
              </div>
              <MovePanel style={uiPrefs.toolheadStyle || "bars"} distances={moveDistances} step={step} setStep={setStep}
                jog={jog} disabled={disabled} btn={btn} onHomeXY={() => home("XY")} />
              <span className="text-[9px] opacity-45 text-center">{moveReason ? `${moveReason} · ` : ""}max 100 mm per jog</span>
            </div>
          ))}
        {tab === "extruder" && <ExtruderPanel {...panelProps} />}
        {tab === "heat" && <HeatersPanel status={panelProps.status} capabilities={panelProps.capabilities} limits={limits || {}} t={t} />}
        {tab === "tune" && <TuningPanel status={panelProps.status} capabilities={panelProps.capabilities} connected={connected} />}
        {tab === "z" && <ZOffsetPanel {...panelProps} />}
        {tab === "level" && <LevelingPanel {...panelProps} />}
        {tab === "goto" && <GoToPanel btn={panelProps.btn} connected={connected} printing={printing} x={x} y={y} z={z} />}
      </div>
      {toolheadStatus && (
        <div className={`mt-2 text-[10px] text-center font-mono ${toolheadStatus.ok ? "opacity-70" : "text-red-400"}`} role="status">{toolheadStatus.message}</div>
      )}
      {message && !toolheadStatus && <div className="mt-2 text-[10px] text-center font-mono opacity-70" role="status">{message}</div>}
    </section>
  );
}
