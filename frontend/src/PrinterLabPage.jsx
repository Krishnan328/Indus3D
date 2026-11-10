import React, { useEffect, useMemo, useState } from "react";
import { Activity, Beaker, CheckCircle2, Clock3, Database, Gauge, Plus, RefreshCw, Save, Thermometer, XCircle } from "lucide-react";
import { API } from "./store";
import { useThemeTokens } from "./theme";

const EMPTY_FORM = {
  label: "", kind: "idle", status: "complete", printer_profile: "", material: "",
  gcode_filename: "", slicer_estimated_seconds: "", notes: "", telemetry_capture: "",
  report: "", photos: "", indus_cpu_pct: "", indus_memory_mb: "",
  mainsail_cpu_pct: "", mainsail_memory_mb: "", actual_time_s: "", energy_wh: "",
  filament_g: "", quality_score: "", extruder_temp_c: "", bed_temp_c: "",
  path_length_mm: "", position_error_mm: "", vibration_rms: "",
  predicted_energy_wh: "", predicted_filament_g: "", predicted_extruder_temp_c: "",
  predicted_bed_temp_c: "", predicted_path_length_mm: "", predicted_position_error_mm: "",
  predicted_vibration_rms: "",
};

const RUN_LABELS = {
  idle: "Idle", heating: "Heating", calibration: "Calibration", print: "Ordinary print", motion: "Motion",
};

function formatNumber(value, suffix = "") {
  if (value === undefined || value === null || value === "") return "—";
  return `${Number(value).toFixed(Number(value) % 1 ? 1 : 0)}${suffix}`;
}

function formatTime(seconds) {
  if (seconds === undefined || seconds === null) return "—";
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

function RecipeCard({ icon: Icon, title, detail, fields }) {
  const t = useThemeTokens();
  return <div className={`${t.cell} p-3 min-w-[200px]`}>
    <div className="flex items-center gap-2 text-xs font-semibold"><Icon size={15} className="text-emerald-500" />{title}</div>
    <p className="text-[11px] opacity-65 mt-2 leading-relaxed">{detail}</p>
    <p className="text-[10px] uppercase tracking-wide opacity-45 mt-2">Capture: {fields}</p>
  </div>;
}

function BudgetLine({ state, limits }) {
  const t = useThemeTokens();
  return <div className={`${t.cell} p-3 flex-1 min-w-[180px]`}>
    <div className="text-xs font-semibold capitalize">{state.replace("_", " ")}</div>
    <div className="mt-2 text-[11px] opacity-65 space-y-1">
      <div>Indus3D CPU ≤ {limits.indus_cpu_pct}%</div>
      <div>Indus3D memory ≤ {limits.indus_memory_mb} MB</div>
    </div>
  </div>;
}

export function PrinterLabPage() {
  const t = useThemeTokens();
  const [data, setData] = useState({ runs: [], baselines: [], default_budgets: {}, active_budgets: {} });
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API}/api/v1/lab/summary`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not load Printer Lab history");
      setData(payload);
      setError("");
    } catch (err) {
      setError(err.message || "Could not load Printer Lab history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const update = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const metrics = useMemo(() => {
    const keys = ["indus_cpu_pct", "indus_memory_mb", "mainsail_cpu_pct", "mainsail_memory_mb", "actual_time_s", "energy_wh", "filament_g", "quality_score", "extruder_temp_c", "bed_temp_c", "path_length_mm", "position_error_mm", "vibration_rms"];
    return Object.fromEntries(keys.filter(key => form[key] !== "").map(key => [key, Number(form[key])]));
  }, [form]);
  const predictions = useMemo(() => {
    const fields = [["predicted_energy_wh", "energy_wh"], ["predicted_filament_g", "filament_g"], ["predicted_extruder_temp_c", "extruder_temp_c"], ["predicted_bed_temp_c", "bed_temp_c"], ["predicted_path_length_mm", "path_length_mm"], ["predicted_position_error_mm", "position_error_mm"], ["predicted_vibration_rms", "vibration_rms"]];
    return Object.fromEntries(fields.filter(([formKey]) => form[formKey] !== "").map(([formKey, apiKey]) => [apiKey, Number(form[formKey])]));
  }, [form]);

  const saveRun = async (event) => {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    const artifacts = {};
    if (form.telemetry_capture) artifacts.telemetry_capture = form.telemetry_capture;
    if (form.report) artifacts.report = form.report;
    if (form.photos) artifacts.photos = form.photos.split("\n").map(value => value.trim()).filter(Boolean);
    try {
      const response = await fetch(`${API}/api/v1/lab/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, slicer_estimated_seconds: form.slicer_estimated_seconds || null, measurements: metrics, predictions, artifacts }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not save run");
      setForm(EMPTY_FORM);
      setNotice(`Saved “${payload.run.label}” to the Printer Lab.`);
      await load();
    } catch (err) {
      setError(err.message || "Could not save run");
    } finally { setSaving(false); }
  };

  const saveBaseline = async (run) => {
    const defaultName = `${RUN_LABELS[run.kind] || run.kind} baseline`;
    const name = window.prompt("Name this baseline", defaultName);
    if (!name) return;
    try {
      const response = await fetch(`${API}/api/v1/lab/baselines`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, run_id: run.id }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not set baseline");
      setNotice(`“${payload.baseline.name}” is now available for comparisons.`);
      await load();
    } catch (err) { setError(err.message || "Could not set baseline"); }
  };

  return <main className="flex-1 min-h-0 overflow-y-auto pr-1 pb-4">
    <section className={`${t.panel} p-5 mb-4`}>
      <div className="flex flex-wrap gap-4 items-start justify-between">
        <div>
          <div className="flex items-center gap-2"><Beaker size={20} className="text-emerald-500" /><h1 className="text-lg font-semibold">Printer Lab</h1></div>
          <p className="text-sm opacity-60 mt-1 max-w-2xl">A persistent history for repeatable tests, measured prints, tool-generated reports, photos, and performance baselines. Recording is passive: this page never controls the printer.</p>
        </div>
        <button onClick={load} className={`${t.btn || t.cell} px-3 py-2 text-xs flex items-center gap-2`}><RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh</button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 mt-5">
        <RecipeCard icon={Clock3} title="Idle baseline" detail="Leave the machine ready and capture an unchanged 10–20 minute window." fields="CPU, memory, temperatures" />
        <RecipeCard icon={Thermometer} title="Heating baseline" detail="Record a normal heat-up separately; do not automate targets from this dashboard." fields="time, energy, CPU, memory" />
        <RecipeCard icon={Activity} title="Calibration" detail="Attach the calibration telemetry, report, sample G-code, and measured result." fields="report, photos, quality" />
        <RecipeCard icon={Gauge} title="Ordinary print" detail="Use a familiar model and material so real timing and consumption stay comparable." fields="time, energy, filament, quality" />
      </div>
    </section>

    {(error || notice) && <div className={`mb-4 px-4 py-3 text-sm ${error ? "bg-red-500/15 text-red-500" : "bg-emerald-500/15 text-emerald-600"} ${t.cell}`}>
      {error || notice}
    </div>}

    <section className="grid grid-cols-1 2xl:grid-cols-[minmax(340px,0.8fr)_minmax(580px,1.4fr)] gap-4">
      <form onSubmit={saveRun} className={`${t.panel} p-5 h-fit`}>
        <div className="flex items-center justify-between mb-4"><h2 className={t.heading}>Record experiment</h2><span className="text-[10px] opacity-50 uppercase tracking-widest">No printer control</span></div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <label className="col-span-2"> <span className={t.label}>Run label</span><input required value={form.label} onChange={e => update("label", e.target.value)} placeholder="Post-hardening idle" className={`${t.cell} w-full px-3 py-2`} /></label>
          <label><span className={t.label}>Test type</span><select value={form.kind} onChange={e => update("kind", e.target.value)} className={`${t.cell} w-full px-3 py-2`}>{Object.entries(RUN_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label><span className={t.label}>Status</span><select value={form.status} onChange={e => update("status", e.target.value)} className={`${t.cell} w-full px-3 py-2`}>{["planned", "capturing", "complete", "archived"].map(value => <option key={value}>{value}</option>)}</select></label>
          <label><span className={t.label}>Printer profile</span><input value={form.printer_profile} onChange={e => update("printer_profile", e.target.value)} placeholder="Voron / server profile" className={`${t.cell} w-full px-3 py-2`} /></label>
          <label><span className={t.label}>Material</span><input value={form.material} onChange={e => update("material", e.target.value)} placeholder="PLA" className={`${t.cell} w-full px-3 py-2`} /></label>
          <label><span className={t.label}>G-code file</span><input value={form.gcode_filename} onChange={e => update("gcode_filename", e.target.value)} placeholder="sample.gcode" className={`${t.cell} w-full px-3 py-2`} /></label>
          <label><span className={t.label}>Slicer estimate (s)</span><input type="number" min="0" value={form.slicer_estimated_seconds} onChange={e => update("slicer_estimated_seconds", e.target.value)} className={`${t.cell} w-full px-3 py-2`} /></label>
          <label className="col-span-2"><span className={t.label}>Notes / real-world measurement</span><textarea value={form.notes} onChange={e => update("notes", e.target.value)} rows="3" placeholder="Observed quality, measured dimensions, changes made…" className={`${t.cell} w-full px-3 py-2 resize-y`} /></label>
        </div>
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer opacity-75 font-medium">Performance and artifact details</summary>
          <div className="grid grid-cols-2 gap-3 mt-3">
            {[['indus_cpu_pct','Indus CPU %'], ['indus_memory_mb','Indus memory MB'], ['mainsail_cpu_pct','Mainsail CPU %'], ['mainsail_memory_mb','Mainsail memory MB'], ['actual_time_s','Actual time (s)'], ['energy_wh','Energy (Wh)'], ['filament_g','Filament (g)'], ['quality_score','Quality score'], ['extruder_temp_c','Actual nozzle °C'], ['bed_temp_c','Actual bed °C'], ['path_length_mm','Actual path (mm)'], ['position_error_mm','Position error (mm)'], ['vibration_rms','Vibration RMS']].map(([key, label]) => <label key={key}><span className={t.label}>{label}</span><input type="number" min="0" step="any" value={form[key]} onChange={e => update(key, e.target.value)} className={`${t.cell} w-full px-3 py-2`} /></label>)}
            <div className="col-span-2 mt-2 pt-3 border-t border-current/10"><span className={t.label}>Predictions for model-error analysis</span><p className="text-[11px] opacity-55 mb-2">Slicer time is already compared to actual time. These optional values are only analyzed; no printer setting is ever changed.</p></div>
            {[['predicted_energy_wh','Predicted energy (Wh)'], ['predicted_filament_g','Predicted filament (g)'], ['predicted_extruder_temp_c','Predicted nozzle °C'], ['predicted_bed_temp_c','Predicted bed °C'], ['predicted_path_length_mm','Predicted path (mm)'], ['predicted_position_error_mm','Predicted position error (mm)'], ['predicted_vibration_rms','Predicted vibration RMS']].map(([key, label]) => <label key={key}><span className={t.label}>{label}</span><input type="number" min="0" step="any" value={form[key]} onChange={e => update(key, e.target.value)} className={`${t.cell} w-full px-3 py-2`} /></label>)}
            <label className="col-span-2"><span className={t.label}>Telemetry capture path</span><input value={form.telemetry_capture} onChange={e => update("telemetry_capture", e.target.value)} placeholder="/var/lib/indus3d/lab/runs/run.jsonl" className={`${t.cell} w-full px-3 py-2`} /></label>
            <label className="col-span-2"><span className={t.label}>Derived report path</span><input value={form.report} onChange={e => update("report", e.target.value)} placeholder="/var/lib/indus3d/lab/reports/run/report.md" className={`${t.cell} w-full px-3 py-2`} /></label>
            <label className="col-span-2"><span className={t.label}>Photo paths (one per line)</span><textarea value={form.photos} onChange={e => update("photos", e.target.value)} rows="2" className={`${t.cell} w-full px-3 py-2 resize-y`} /></label>
          </div>
        </details>
        <button disabled={saving} className={`mt-5 w-full py-2.5 flex justify-center items-center gap-2 text-sm font-semibold ${t.accentBg} ${t.btn || "rounded"} disabled:opacity-60`}><Save size={15} />{saving ? "Saving…" : "Save experiment"}</button>
      </form>

      <div className="space-y-4 min-w-0">
        <section className={`${t.panel} p-5`}>
          <div className="flex items-center gap-2 mb-4"><Gauge size={18} className="text-blue-500" /><h2 className={t.heading}>Provisional resource budgets</h2></div>
          <p className="text-xs opacity-60 mb-3">These conservative starting targets are evaluated against captured Indus3D values. {data.baselines.length ? `Using the most recent baseline: ${data.baselines[0].name}.` : "Set a baseline to lock these targets to a measured reference."}</p>
          <div className="flex flex-wrap gap-3">{Object.entries(data.active_budgets || data.default_budgets || {}).map(([state, limits]) => <BudgetLine key={state} state={state} limits={limits} />)}</div>
        </section>
        <section className={`${t.panel} p-5`}>
          <div className="flex items-center justify-between gap-3 mb-4"><div className="flex items-center gap-2"><Database size={18} className="text-violet-500" /><h2 className={t.heading}>Experiment history</h2></div><span className="text-xs opacity-50">{data.runs.length} recorded</span></div>
          {loading ? <div className="text-sm opacity-50 py-8 text-center">Loading lab history…</div> : data.runs.length === 0 ? <div className="text-sm opacity-50 py-8 text-center">No experiments yet. Start with a passive idle baseline.</div> : <div className="space-y-3">{data.runs.map(run => {
            const m = run.measurements || {}; const comparison = run.comparison?.metrics || {}; const isBaseline = data.baselines.some(b => b.run.id === run.id);
            return <article key={run.id} className={`${t.cell} p-4`}>
              <div className="flex flex-wrap justify-between gap-3"><div><div className="flex items-center gap-2"><span className="font-semibold text-sm">{run.label}</span><span className="text-[10px] px-2 py-0.5 rounded-full bg-black/10 uppercase tracking-wide">{RUN_LABELS[run.kind] || run.kind}</span>{isBaseline && <span className="text-[10px] text-emerald-600 flex items-center gap-1"><CheckCircle2 size={12} /> baseline</span>}</div><p className="text-xs opacity-55 mt-1">{new Date(run.created_at * 1000).toLocaleString()} · {run.status}{run.gcode_filename ? ` · ${run.gcode_filename}` : ""}</p></div>{!isBaseline && <button onClick={() => saveBaseline(run)} className="text-xs px-2.5 py-1.5 border border-current/20 rounded hover:bg-black/5">Set baseline</button>}</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-xs"><div><span className={t.label}>Indus CPU</span>{formatNumber(m.indus_cpu_pct, "%")}</div><div><span className={t.label}>Indus memory</span>{formatNumber(m.indus_memory_mb, " MB")}</div><div><span className={t.label}>Mainsail CPU</span>{formatNumber(m.mainsail_cpu_pct, "%")}</div><div><span className={t.label}>Actual time</span>{formatTime(m.actual_time_s)}</div></div>
              {Object.keys(comparison).length > 0 && <div className="mt-3 text-[11px] opacity-70 border-t border-current/10 pt-2">vs {run.comparison.baseline_name}: {Object.entries(comparison).slice(0, 4).map(([key, value]) => <span key={key} className="mr-3">{key.replaceAll("_", " ")} <strong className={value.delta > 0 ? "text-amber-500" : "text-emerald-600"}>{value.delta > 0 ? "+" : ""}{formatNumber(value.delta_pct, "%")}</strong></span>)}</div>}
              {run.analysis?.metrics_compared > 0 && <div className="mt-3 text-[11px] border-t border-current/10 pt-2"><span className="opacity-55">Prediction model error: </span><strong>{formatNumber(run.analysis.mean_absolute_percentage_error, "%")}</strong> across {run.analysis.metrics_compared} measure{run.analysis.metrics_compared === 1 ? "" : "s"}. {run.analysis.recommendations?.slice(0, 1).map(item => <span key={item} className="block opacity-70 mt-1">Recommendation: {item}</span>)}</div>}
              {run.notes && <p className="text-xs opacity-60 mt-3 whitespace-pre-wrap">{run.notes}</p>}
            </article>;
          })}</div>}
        </section>
      </div>
    </section>
  </main>;
}
