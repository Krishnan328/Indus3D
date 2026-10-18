import React, { useEffect, useState } from "react";
import { X, Sparkles, AlertTriangle, CheckCircle2, Ruler, Thermometer, Grid3X3, Save, Upload, Activity, Gauge } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

const STEPS = [
  ["home", "Home axes", "Homes the printer before probing or tuning."],
  ["bed_mesh", "Bed mesh", "Runs G28 then BED_MESH_CALIBRATE. A configured probe is required."],
  ["pid_hotend", "Hotend PID", "Runs Klipper PID_CALIBRATE at the chosen nozzle temperature."],
  ["pid_bed", "Bed PID", "Runs Klipper PID_CALIBRATE at the chosen bed temperature."],
  ["input_shaping", "Input Shaping (ADXL)", "Runs SHAPER_CALIBRATE if an accelerometer is configured."],
  ["save", "Save Klipper config", "Writes completed mesh/PID/Shaper values through SAVE_CONFIG; Klipper restarts."],
];

export function CalibrationWizard({ onClose }) {
  const t = useThemeTokens();
  const status = useStore((s) => s.calibrationStatus);
  const fetchStatus = useStore((s) => s.fetchCalibrationStatus);
  const runStep = useStore((s) => s.runCalibrationStep);
  const uploadFlowSample = useStore((s) => s.uploadFlowSample);
  const uploadPATest = useStore((s) => s.uploadPATest);
  const [hotendInput, setHotendInput] = useState(null);
  const [bedInput, setBedInput] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [expectedInput, setExpectedInput] = useState(null);
  const [measured, setMeasured] = useState("");
  const [flow, setFlow] = useState(null);

  // PA tuning state
  const [paStart, setPaStart] = useState(0.0);
  const [paEnd, setPaEnd] = useState(0.1);
  const [paStep, setPaStep] = useState(0.005);
  const [paResult, setPaResult] = useState("");
  const [paApplied, setPaApplied] = useState(null);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);
  const hotend = hotendInput ?? status.defaults?.hotend_c ?? 200;
  const bed = bedInput ?? status.defaults?.bed_c ?? 60;
  const expected = expectedInput ?? status.defaults?.line_width_mm ?? 0.42;

  const confirmAndRun = async (step) => {
    const labels = { bed_mesh: "move the probe across the bed", pid_hotend: "heat the nozzle and run a PID cycle", pid_bed: "heat the bed and run a PID cycle", input_shaping: "vibrate the toolhead to measure resonances", save: "write calibration values and restart Klipper" };
    if (labels[step] && !window.confirm(`This will ${labels[step]}. Clear the bed and supervise the printer. Continue?`)) return;
    setBusy(step); setMessage("");
    const result = await runStep(step, step === "pid_hotend" ? { target: hotend } : step === "pid_bed" ? { target: bed } : {});
    setMessage(result.error || result.detail || (result.simulated ? `${step} queued in simulation` : `${step.replaceAll("_", " ")} command sent`));
    setBusy(""); fetchStatus();
  };

  const makeFlowSample = async () => {
    if (!window.confirm("Upload the 20 mm single-wall flow sample? It will not start automatically.")) return;
    setBusy("flow"); setMessage("");
    const result = await uploadFlowSample();
    setMessage(result.error || (result.status === "simulation" ? "Simulation: sample generated (hardware measurement is unavailable)." : "Flow sample uploaded. Start indus_flow_sample.gcode when ready."));
    setBusy("");
  };

  const calculateFlow = () => {
    const actual = Number(measured);
    if (!actual || actual <= 0) return;
    const recommendation = Math.round(Math.max(85, Math.min(115, (expected / actual) * 100)));
    setFlow(recommendation);
  };

  const applyFlow = async () => {
    if (flow === null || !window.confirm(`Apply M221 S${flow} for this session? Put the calibrated value in your slicer for a permanent result.`)) return;
    setBusy("apply-flow");
    const result = await runStep("apply_flow", { flow });
    setMessage(result.error || `M221 S${flow} sent. Update your slicer flow to make it permanent.`);
    setBusy("");
  };

  // PA tuning actions
  const makePATest = async () => {
    if (!window.confirm(`Generate PA test pattern (${paStart}–${paEnd}, step ${paStep})? The file will be uploaded but NOT started automatically.`)) return;
    setBusy("pa"); setMessage("");
    const result = await uploadPATest({
      pa_start: paStart, pa_end: paEnd, pa_step: paStep,
      hotend_temp: Number(hotend), bed_temp: Number(bed),
    });
    setMessage(result.error || (result.status === "simulation"
      ? "Simulation: PA test generated (hardware print is unavailable)."
      : `${result.filename} uploaded. Start it from the file manager when ready.`));
    setBusy("");
  };

  const applyPA = async () => {
    const val = Number(paResult);
    if (isNaN(val) || val < 0 || val > 2.0) { setMessage("Enter a PA value between 0 and 2.0"); return; }
    setBusy("apply-pa");
    const result = await runStep("apply_pa", { pa: val });
    setMessage(result.error || `SET_PRESSURE_ADVANCE ADVANCE=${val.toFixed(4)} sent. Add this to your printer.cfg [extruder] section to make it permanent.`);
    setPaApplied(val);
    setBusy("");
  };

  const lineCount = Math.max(0, Math.floor((paEnd - paStart) / paStep) + 1);

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-5 bg-black/60 backdrop-blur-sm">
      <div className={`w-full max-w-4xl max-h-[90vh] overflow-y-auto p-5 ${t.panel}`}>
        <header className="flex items-start justify-between gap-4 mb-5">
          <div><div className="flex items-center gap-2 text-violet-400"><Sparkles size={19} /><h2 className={t.heading}>Guided Calibration</h2></div><p className="text-xs opacity-60 mt-1">Klipper-native calibration with explicit, supervised steps—not a black-box promise.</p></div>
          <button onClick={onClose} className="p-1 opacity-60 hover:opacity-100"><X size={20} /></button>
        </header>
        <div className={`flex gap-2 p-3 mb-5 text-xs ${t.cell} ${status.ready ? "border-green-600" : "border-amber-500"}`}>
          {status.ready ? <CheckCircle2 size={16} className="text-green-500 shrink-0" /> : <AlertTriangle size={16} className="text-amber-500 shrink-0" />}
          <span>{status.ready ? (status.simulated ? "Simulation is ready. Commands are visualised only." : "Printer is idle. Clear the bed and stay with the printer while each step runs.") : `Unavailable while printer state is '${status.print_state}'. Finish or cancel the active print first.`}</span>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <section className="flex flex-col gap-2">
            <h3 className={t.heading}>Machine tuning</h3>
            {STEPS.map(([id, title, description]) => (
              <div key={id} className={`flex items-center gap-3 p-3 ${t.cell}`}>
                {id === "bed_mesh" ? <Grid3X3 size={16} /> : id.startsWith("pid") ? <Thermometer size={16} /> : id === "save" ? <Save size={16} /> : id === "input_shaping" ? <Activity size={16} /> : <CheckCircle2 size={16} />}
                <div className="flex-1"><div className="text-xs font-bold">{title}</div><div className="text-[10px] opacity-60 mt-0.5">{description}</div></div>
                {id === "pid_hotend" && <input value={hotend} onChange={(e) => setHotendInput(e.target.value)} type="number" min="150" max="300" className={`w-14 px-1 py-1 text-xs ${t.cell}`} title="Hotend PID target" />}
                {id === "pid_bed" && <input value={bed} onChange={(e) => setBedInput(e.target.value)} type="number" min="40" max="120" className={`w-14 px-1 py-1 text-xs ${t.cell}`} title="Bed PID target" />}
                <button disabled={!status.ready || !!busy} onClick={() => confirmAndRun(id)} className={`px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} bg-blue-600 text-white disabled:opacity-40`}>{busy === id ? "…" : "Run"}</button>
              </div>
            ))}
          </section>
          <section className="flex flex-col gap-3">
            {/* ── Pressure Advance ─────────────────────────── */}
            <div><h3 className={t.heading}>Pressure Advance tuning</h3><p className="text-[10px] opacity-60 mt-1">Generates a slow→fast→slow test pattern. Each line uses a different PA value. Pick the line where speed transitions are cleanest.</p></div>
            <div className={`p-3 ${t.cell}`}>
              <div className="flex items-center gap-2 text-xs font-bold"><Gauge size={15} />PA test pattern</div>
              <div className="grid grid-cols-3 gap-2 mt-2">
                <label className="text-[10px]">Start K<input value={paStart} onChange={(e) => setPaStart(Number(e.target.value))} type="number" step="0.005" min="0" max="2" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label>
                <label className="text-[10px]">End K<input value={paEnd} onChange={(e) => setPaEnd(Number(e.target.value))} type="number" step="0.005" min="0" max="2" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label>
                <label className="text-[10px]">Step<input value={paStep} onChange={(e) => setPaStep(Number(e.target.value))} type="number" step="0.001" min="0.001" max="0.1" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label>
              </div>
              <p className="text-[10px] opacity-50 mt-1">{lineCount} test lines will be printed</p>
              <button disabled={!status.ready || !!busy} onClick={makePATest} className={`mt-2 px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} bg-violet-600 text-white disabled:opacity-40`}><Upload size={12} className="inline mr-1" />{busy === "pa" ? "…" : "Generate & Upload"}</button>
            </div>
            <div className={`p-3 ${t.cell}`}>
              <div className="text-xs font-bold mb-2">Apply result</div>
              <div className="flex gap-2 items-end">
                <label className="text-[10px] flex-1">Best K value<input value={paResult} onChange={(e) => setPaResult(e.target.value)} type="number" step="0.001" min="0" max="2" placeholder="e.g. 0.045" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label>
                <button disabled={!status.ready || !!busy || !paResult} onClick={applyPA} className={`px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} bg-emerald-600 text-white disabled:opacity-40`}>{busy === "apply-pa" ? "…" : "Apply"}</button>
              </div>
              {paApplied !== null && <p className="text-[10px] mt-2 opacity-70">Applied PA={paApplied.toFixed(4)} for this session. To make it permanent, add <code>pressure_advance: {paApplied.toFixed(4)}</code> to the <code>[extruder]</code> section in printer.cfg, then SAVE_CONFIG.</p>}
            </div>

            {/* ── Flow validation ──────────────────────────── */}
            <div><h3 className={t.heading}>Flow validation</h3><p className="text-[10px] opacity-60 mt-1">A camera or flow sensor is needed for fully automatic flow calibration. With ordinary Klipper hardware, measure this sample with calipers.</p></div>
            <div className={`p-3 ${t.cell}`}>
              <div className="flex items-center gap-2 text-xs font-bold"><Ruler size={15} />Single-wall sample</div>
              <p className="text-[10px] opacity-60 my-2">Creates and uploads <code>indus_flow_sample.gcode</code> but never starts it automatically.</p>
              <button disabled={!status.ready || !!busy} onClick={makeFlowSample} className={`px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} bg-violet-600 text-white disabled:opacity-40`}><Upload size={12} className="inline mr-1" />{busy === "flow" ? "…" : "Upload sample"}</button>
            </div>
            <div className={`p-3 ${t.cell}`}>
              <div className="grid grid-cols-2 gap-2"><label className="text-[10px]">Expected wall (mm)<input value={expected} onChange={(e) => setExpectedInput(Number(e.target.value))} type="number" step="0.01" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label><label className="text-[10px]">Measured wall (mm)<input value={measured} onChange={(e) => setMeasured(e.target.value)} type="number" step="0.01" className={`block w-full mt-1 px-2 py-1 ${t.cell}`} /></label></div>
              <div className="flex gap-2 mt-3"><button onClick={calculateFlow} className={`px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} ${t.cell}`}>Calculate</button>{flow !== null && <button disabled={!!busy} onClick={applyFlow} className={`px-3 py-1.5 text-[10px] font-bold uppercase ${t.chip} bg-emerald-600 text-white`}>Apply M221 S{flow}</button>}</div>
              {flow !== null && <p className="text-[10px] mt-2 opacity-70">Temporary recommendation: {flow}%. Put this result in the slicer after confirming it on a second sample.</p>}
            </div>
          </section>
        </div>
        <p className="mt-4 text-[10px] opacity-50">{status.note || "PID and bed mesh values only become persistent after SAVE_CONFIG. Input shaping and flow require additional measurement hardware or a validated test."}</p>
        {message && <div className="mt-3 text-xs font-mono text-center text-amber-400">{message}</div>}
      </div>
    </div>
  );
}
