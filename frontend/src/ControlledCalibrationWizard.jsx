import React, { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, ClipboardCheck, FileCheck2, FlaskConical, LockKeyhole, PlayCircle, RefreshCw, Save, ShieldCheck, X } from "lucide-react";
import { API } from "./store";
import { useThemeTokens } from "./theme";

const PREFLIGHT = [
  ["operator_present", "I am at the printer and will supervise every manual action."],
  ["bed_clear", "The bed, nozzle path, and surrounding area are physically clear."],
  ["emergency_stop_accessible", "An emergency stop/power-off path is accessible."],
  ["no_active_job_confirmed", "I confirmed there is no active or paused job."],
  ["rollback_snapshot_confirmed", "I understand a profile snapshot is recorded for manual rollback comparison."],
];

export function ControlledCalibrationWizard({ onClose }) {
  const t = useThemeTokens();
  const [status, setStatus] = useState(null);
  const [checks, setChecks] = useState(Object.fromEntries(PREFLIGHT.map(([key]) => [key, false])));
  const [workflow, setWorkflow] = useState(null);
  const [plan, setPlan] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportPath, setReportPath] = useState("");
  const [operator, setOperator] = useState("");
  const [partReviewed, setPartReviewed] = useState(false);

  const request = async (path, options = {}) => {
    const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Calibration workflow request failed");
    return payload;
  };
  const refresh = async () => {
    try { setStatus(await request("/api/v1/calibration/workflow/status")); setMessage(""); }
    catch (error) { setMessage(error.message); }
  };
  useEffect(() => { refresh(); }, []);

  const start = async () => {
    setBusy(true); setMessage("");
    try {
      const data = await request("/api/v1/calibration/workflow/sessions", { method: "POST", body: JSON.stringify({ preflight: checks }) });
      setWorkflow(data.workflow); setPlan(null);
      setMessage("Safety session prepared. Low-risk collection and review-plan generation are now available; nothing has been sent to the printer.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  const collect = async () => {
    setBusy(true); setMessage("");
    try { const data = await request(`/api/v1/calibration/workflow/sessions/${workflow.id}/collect`, { method: "POST" }); setWorkflow(data.workflow); setMessage("Passive telemetry snapshot recorded in this workflow."); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const generatePlan = async (phase) => {
    setBusy(true); setMessage("");
    try {
      const target = phase === "pid_hotend" ? 200 : phase === "pid_bed" ? 60 : undefined;
      const data = await request(`/api/v1/calibration/workflow/sessions/${workflow.id}/command-plan`, { method: "POST", body: JSON.stringify({ phase, ...(target ? { target } : {}) }) });
      setPlan(data.plan); setMessage("Review plan generated. It has not been sent, uploaded, queued, or persisted.");
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const recordValidation = async () => {
    setBusy(true); setMessage("");
    try {
      const data = await request(`/api/v1/calibration/workflow/sessions/${workflow.id}/validation`, { method: "POST", body: JSON.stringify({ report_path: reportPath, operator_reviewed_part: partReviewed, predictions: {}, measurements: {} }) });
      setWorkflow(data.workflow); setMessage("Final validation evidence recorded. Approval can be recorded after you review the report and part.");
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const approve = async () => {
    setBusy(true); setMessage("");
    try { const data = await request(`/api/v1/calibration/workflow/sessions/${workflow.id}/persistence-approval`, { method: "POST", body: JSON.stringify({ operator }) }); setWorkflow(data.workflow); setMessage("Persistence approval recorded. No Klipper setting was changed; use the manual, supervised configuration path with this evidence."); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };

  const ready = status?.readiness?.ready;
  const phases = status?.phases || {};
  const allChecked = PREFLIGHT.every(([key]) => checks[key]);
  return <div className="absolute inset-0 z-50 flex items-center justify-center p-5 bg-black/60 backdrop-blur-sm">
    <div className={`w-full max-w-5xl max-h-[90vh] overflow-y-auto p-5 ${t.panel}`}>
      <header className="flex items-start justify-between gap-4 mb-5"><div><div className="flex items-center gap-2 text-violet-400"><ShieldCheck size={19} /><h2 className={t.heading}>Controlled calibration</h2></div><p className="text-xs opacity-60 mt-1">Analysis-first workflow. It prepares review plans and evidence; it never executes, uploads, or persists printer commands.</p></div><button onClick={onClose} className="p-1 opacity-60 hover:opacity-100"><X size={20} /></button></header>
      <div className={`flex items-center justify-between gap-3 p-3 mb-4 text-xs ${t.cell} ${ready ? "border-green-600" : "border-amber-500"}`}><div className="flex gap-2"><Activity size={16} className={ready ? "text-green-500" : "text-amber-500"}/><span>{ready ? (status?.readiness?.simulated ? "Simulation is ready." : "Klipper is ready and no job is active.") : (status?.readiness?.reason || "Checking printer readiness…")}</span></div><button onClick={refresh} className="p-1 opacity-60 hover:opacity-100"><RefreshCw size={15}/></button></div>
      <div className="grid lg:grid-cols-[0.85fr_1.15fr] gap-4">
        <section className={`p-4 ${t.cell}`}><div className="flex gap-2 items-center"><ClipboardCheck size={16}/><h3 className={t.heading}>Physical preflight</h3></div><p className="text-[11px] opacity-60 mt-2">All acknowledgements and a rollback profile snapshot are required before a command plan can be generated.</p><div className="space-y-2 mt-3">{PREFLIGHT.map(([key, label]) => <label key={key} className="flex gap-2 text-xs items-start"><input type="checkbox" checked={checks[key]} onChange={event => setChecks(current => ({ ...current, [key]: event.target.checked }))} /><span>{label}</span></label>)}</div><button disabled={!ready || !allChecked || busy} onClick={start} className={`mt-4 w-full px-3 py-2 text-xs font-bold ${t.chip} bg-blue-600 text-white disabled:opacity-40`}><LockKeyhole size={13} className="inline mr-1"/>{workflow ? "Start new safety session" : "Prepare safety session"}</button>{workflow && <><div className="text-[10px] opacity-55 mt-3 break-all">Session {workflow.id}</div><button disabled={busy} onClick={collect} className={`mt-2 w-full px-3 py-2 text-xs font-bold ${t.chip} ${t.cell}`}><RefreshCw size={12} className="inline mr-1"/>Collect passive snapshot</button></>}</section>
        <section className="space-y-3"><div className={`p-4 ${t.cell}`}><div className="flex gap-2 items-center"><FlaskConical size={16}/><h3 className={t.heading}>Guided phases</h3></div><p className="text-[11px] opacity-60 mt-2">Each button generates a bounded review plan only. Flow and pressure advance deliberately route to the offline review-only test library.</p><div className="grid sm:grid-cols-2 gap-2 mt-3">{Object.entries(phases).map(([id, item]) => <div key={id} className="border border-current/10 p-2"><div className="text-xs font-semibold">{item.label}</div><p className="text-[10px] opacity-60 mt-1">{item.note}</p><button disabled={!workflow || busy} onClick={() => generatePlan(id)} className="mt-2 text-[10px] px-2 py-1 border border-current/20 rounded disabled:opacity-40">Generate review plan</button></div>)}</div></div>
          {plan && <div className={`p-4 ${t.cell}`}><div className="flex gap-2 items-center"><FileCheck2 size={16}/><h3 className={t.heading}>{plan.label}</h3></div><p className="text-[11px] opacity-60 mt-2">{plan.note}</p>{plan.command ? <pre className="mt-3 text-xs p-3 bg-black/10 overflow-x-auto whitespace-pre-wrap">{plan.command}</pre> : <p className="mt-3 text-xs font-mono opacity-70">No G-code is generated for this phase. {plan.note}</p>}<p className="text-[10px] text-amber-600 mt-3">{plan.required_next_action}</p></div>}
          <div className={`p-4 ${t.cell}`}><div className="flex gap-2 items-center"><PlayCircle size={16}/><h3 className={t.heading}>Final validation and approval</h3></div><p className="text-[11px] opacity-60 mt-2">After an operator-approved validation print, attach its report and confirm you inspected the part. Approval is only a record; persistence stays manual and supervised.</p><input value={reportPath} onChange={event => setReportPath(event.target.value)} placeholder="/var/lib/indus3d/lab/reports/validation/report.md" className={`${t.cell} w-full px-3 py-2 text-xs mt-3`}/><label className="flex gap-2 text-xs mt-2"><input type="checkbox" checked={partReviewed} onChange={event => setPartReviewed(event.target.checked)}/>I reviewed the finished validation part and its report.</label><button disabled={!workflow || !reportPath || !partReviewed || busy} onClick={recordValidation} className={`mt-3 px-3 py-2 text-xs font-bold ${t.chip} ${t.cell} disabled:opacity-40`}>Record validation</button><div className="flex gap-2 mt-3"><input value={operator} onChange={event => setOperator(event.target.value)} placeholder="Approving operator" className={`${t.cell} flex-1 px-3 py-2 text-xs`}/><button disabled={!workflow || workflow.status !== "validated" || !operator || busy} onClick={approve} className={`px-3 py-2 text-xs font-bold ${t.chip} bg-emerald-600 text-white disabled:opacity-40`}><Save size={12} className="inline mr-1"/>Approve</button></div></div>
        </section>
      </div>
      {message && <div className="mt-4 text-xs text-center text-amber-500">{message}</div>}
    </div>
  </div>;
}
