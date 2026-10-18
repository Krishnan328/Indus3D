import React, { useEffect, useState } from "react";
import { Waves, PlayCircle, Check, Scale } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

/** Guides Klipper's own ADXL345-based Y-axis SHAPER_CALIBRATE workflow. */
export function ShaperTuner() {
  const current = useStore((s) => s.shaperCurrent);
  const job = useStore((s) => s.shaperJob);
  const fetchCurrent = useStore((s) => s.fetchShaperCurrent);
  const fetchStatus = useStore((s) => s.fetchShaperStatus);
  const startCalibration = useStore((s) => s.startShaperCalibration);
  const applyResult = useStore((s) => s.applyShaperResult);
  const setBedMass = useStore((s) => s.setShaperBedMass);
  const t = useThemeTokens();
  const [massInput, setMassInput] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => { fetchCurrent(); fetchStatus(); }, [fetchCurrent, fetchStatus]);
  useEffect(() => {
    if (job.status !== "running") return undefined;
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [job.status, fetchStatus]);

  const start = async () => {
    if (!window.confirm("This moves the printer for Klipper's Y-axis resonance test. Clear the bed and supervise it. Continue?")) return;
    const result = await startCalibration();
    setMessage(result.error || (result.status === "started" ? "Calibration started; waiting for Klipper's recommendation." : "Calibration is already running."));
    fetchStatus();
  };

  const apply = async () => {
    if (!job.result || !window.confirm(`Save ${job.result.shaper_type} at ${job.result.freq.toFixed(1)} Hz as the Y-axis baseline?`)) return;
    const result = await applyResult(job.result.shaper_type, job.result.freq);
    setMessage(result.error || (result.applied ? "Saved and loaded into the quality controller." : "Could not save the recommendation."));
  };

  const saveMass = async () => {
    const grams = Number(massInput);
    if (!Number.isFinite(grams) || grams <= 0) return;
    const result = await setBedMass(grams);
    setMessage(result.error || (result.applied ? "Bed mass saved." : "Could not save bed mass."));
    if (result.applied) setMassInput("");
  };

  return (
    <section className={`p-4 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-indigo-400"><Waves size={16} /><h3 className={t.heading}>Shaper Tuner</h3></div>
      <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs mb-3">
        <div className={`p-2 ${t.cell}`}><span className={t.label}>Y freq</span>{current.freq > 0 ? `${current.freq.toFixed(1)} Hz` : "unset"}</div>
        <div className={`p-2 ${t.cell}`}><span className={t.label}>Shaper</span>{current.shaper_type}</div>
        <div className={`p-2 ${t.cell}`}><span className={t.label}>Bed mass</span>{current.bed_mass_g > 0 ? `${current.bed_mass_g.toFixed(0)} g` : "unset"}</div>
      </div>

      {job.status === "running" ? (
        <div className="flex items-center gap-2 text-xs opacity-70 py-2"><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />Calibrating — this can take a minute or two…</div>
      ) : job.status === "done" && job.result ? (
        <div className="flex flex-col gap-2"><div className={`p-2 text-center text-xs font-mono ${t.cell}`}>Recommended: <b>{job.result.shaper_type}</b> @ <b>{job.result.freq.toFixed(1)} Hz</b></div><button onClick={apply} className={`w-full py-2 font-bold text-xs uppercase tracking-widest text-white ${t.chip} bg-emerald-700 hover:bg-emerald-600`}>Apply recommendation</button></div>
      ) : (
        <><button onClick={start} className={`w-full flex items-center justify-center gap-2 py-2 font-bold text-xs uppercase tracking-widest text-white ${t.chip} bg-indigo-700 hover:bg-indigo-600`}><PlayCircle size={14} />Run SHAPER_CALIBRATE (Y)</button>{job.error && <p className="text-[10px] text-red-400 mt-2">{job.error}</p>}</>
      )}

      <div className={`mt-3 pt-3 flex items-center gap-2 border-t ${t.border}`}><Scale size={13} className="opacity-50 shrink-0" /><input type="number" value={massInput} onChange={(e) => setMassInput(e.target.value)} placeholder="Bed mass (g)" className={`flex-1 px-2 py-1 text-xs font-mono outline-none ${t.cell}`} /><button onClick={saveMass} className={`px-3 py-1 text-[10px] font-bold uppercase ${t.chip} bg-gray-700 hover:bg-gray-600 text-white`}>Save</button></div>
      <p className="text-[10px] opacity-55 mt-2">Empty bed only. Klipper performs the accelerometer analysis; Indus3D reads and saves its recommendation.</p>
      {message && <p className="text-[10px] mt-2 opacity-70">{message}</p>}
    </section>
  );
}
