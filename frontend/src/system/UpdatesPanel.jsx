import React, { useState } from "react";
import { Download, Loader2, Wrench } from "lucide-react";
import { useStore } from "../store";
import { useThemeTokens } from "../theme";
import { Btn, Card, ConfirmDialog, Resource } from "./shared";
import { printBusyState } from "./format";

function JobBox({ job, busy }) {
  const t = useThemeTokens();
  if (!job && !busy) return null;
  const running = job?.state === "running" || (!job && busy);
  const tone = running ? "border-blue-500/50 bg-blue-500/10" : job?.state === "done" ? "border-emerald-500/50 bg-emerald-500/10"
    : job?.state === "unknown" ? "border-amber-500/50 bg-amber-500/10" : "border-red-500/50 bg-red-500/10";
  return (
    <div className={`p-3 mb-3 text-xs rounded border flex items-center gap-2 ${tone}`} role="status">
      {running && <Loader2 size={14} className="animate-spin shrink-0" />}
      <div>
        {running
          ? <>Updating <b>{job?.component || "software"}</b>... Moonraker reports no percentage, so this page watches its status. Do not power off.</>
          : <>{job.message}</>}
      </div>
      {!running && <span className={`ml-auto text-[10px] opacity-60 ${t.label}`}>{job.state}</span>}
    </div>
  );
}

export function UpdatesPanel() {
  const res = useStore((s) => s.systemData.updates);
  const startUpdate = useStore((s) => s.startUpdate);
  const recoverComponent = useStore((s) => s.recoverComponent);
  const busyPath = useStore((s) => s.systemBusy);
  const refresh = useStore((s) => s.refreshSystem);
  const printState = useStore((s) => s.telemetry?.state);
  const printing = printBusyState(printState);
  const t = useThemeTokens();
  const [pending, setPending] = useState(null);       // {kind: "update"|"recover", name}
  const [hard, setHard] = useState(false);

  const run = async () => {
    const p = pending;
    setPending(null);
    if (p.kind === "update") await startUpdate(p.name);
    else await recoverComponent(p.name, hard);
    setHard(false);
  };

  return (
    <Resource res={res} what="The update manager">
      {(d) => {
        const updating = d.job?.state === "running" || d.busy;
        const disabled = printing || updating || !!busyPath;
        const why = printing ? "Updates are refused during a print" : updating ? "An update is running" : "";
        return (
          <Card title="Software updates"
            right={<>
              <Btn onClick={() => refresh("updates")} title="Re-read the update status">Refresh</Btn>
              <Btn disabled={disabled || d.pending.length === 0} title={why || "Update everything that has an update"}
                onClick={() => setPending({ kind: "update", name: "full" })}><Download size={11} />Update all{d.pending.length ? ` (${d.pending.length})` : ""}</Btn>
            </>}>
            <JobBox job={d.job} busy={d.busy} />
            {printing && <p className="p-2 mb-3 text-xs text-amber-500 border border-amber-500/40 rounded">A print is active: updates are refused until it ends.</p>}
            <ul className="divide-y divide-gray-500/20">
              {d.components.map((c) => (
                <li key={c.name} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{c.name}</span>
                    <span className="text-[10px] opacity-50">{c.type}{c.channel ? ` / ${c.channel}` : ""}</span>
                    {c.name === "system"
                      ? <span className="text-xs opacity-80">{c.package_count ? `${c.package_count} package(s) to upgrade` : "up to date"}</span>
                      : <span className="text-xs font-mono opacity-80 break-all">{c.version || "?"}{c.update_available ? ` → ${c.remote_version || "newer commit"}` : ""}</span>}
                    {c.update_available
                      ? <span className={`text-[10px] px-2 py-0.5 ${t.chip} bg-blue-500/20 text-blue-400`}>update available{c.commits_behind ? `, ${c.commits_behind} commits` : ""}</span>
                      : <span className={`text-[10px] px-2 py-0.5 ${t.chip} bg-emerald-500/15 text-emerald-500`}>current</span>}
                    <div className="ml-auto flex gap-1">
                      <Btn disabled={disabled || !c.update_available || c.is_valid === false} title={why || (c.is_valid === false ? "Moonraker marked this repository invalid" : `Update ${c.name}`)}
                        onClick={() => setPending({ kind: "update", name: c.name })}><Download size={11} />Update</Btn>
                      {c.recoverable && (c.is_dirty || c.corrupt || c.is_valid === false) && (
                        <Btn danger disabled={disabled} title="Repair this git repository" onClick={() => setPending({ kind: "recover", name: c.name })}><Wrench size={11} />Recover</Btn>
                      )}
                    </div>
                  </div>
                  {c.recent_commits?.length > 0 && c.update_available && (
                    <ul className="mt-1 ml-1 text-[11px] opacity-60 list-disc list-inside">
                      {c.recent_commits.map((m, i) => <li key={i} className="truncate">{m.subject}{m.author ? ` (${m.author})` : ""}</li>)}
                    </ul>
                  )}
                  {c.package_list?.length > 0 && c.update_available && <p className="mt-1 text-[11px] opacity-60 break-words">{c.package_list.join(", ")}</p>}
                  {[...(c.warnings || []), ...(c.anomalies || [])].map((w, i) => <p key={i} className="mt-1 text-[11px] text-amber-500">{w}</p>)}
                </li>
              ))}
            </ul>
            {d.github?.remaining != null && d.github.remaining < 10 && <p className="mt-2 text-[11px] text-amber-500">GitHub API allowance is low ({d.github.remaining} left): update checks may fail for a while.</p>}
            {pending && (
              <ConfirmDialog danger title={pending.kind === "recover" ? `Recover ${pending.name}?` : pending.name === "full" ? "Update everything?" : `Update ${pending.name}?`}
                confirmLabel={pending.kind === "recover" ? "Recover" : "Update"}
                body={pending.kind === "recover" ? (
                  <>
                    <p>Moonraker will repair the git repository of <b>{pending.name}</b>.</p>
                    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={hard} onChange={(e) => setHard(e.target.checked)} />Hard recovery: delete the repository and clone it again (needs internet, local changes are lost)</label>
                  </>
                ) : (
                  <>
                    <p>{pending.name === "full" ? "Moonraker will update every component listed above." : <>Moonraker will update <b>{pending.name}</b>.</>} Klipper and Moonraker restart afterwards.</p>
                    <p>Nothing is printing right now. Leave the printer powered while this runs; it can take several minutes.</p>
                  </>
                )}
                onConfirm={run} onCancel={() => { setPending(null); setHard(false); }} />
            )}
          </Card>
        );
      }}
    </Resource>
  );
}
