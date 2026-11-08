import React, { useEffect, useRef, useState } from "react";
import { Play, Pause, Trash2, ChevronsUp, Plus, GripVertical, AlertTriangle, Copy, Info, Layers } from "lucide-react";
import { useStore } from "../store";
import { formatDuration, formatFilament, formatClock, moveItem } from "./filesLogic";
import { Btn } from "./ui";
import { useUi } from "./useUi";

const CHIP = {
  ready: ["Ready", "bg-emerald-700 text-white"],
  paused: ["Paused", "bg-amber-600 text-white"],
  loading: ["Loading", "bg-sky-700 text-white"],
  starting: ["Starting", "bg-sky-700 text-white"],
};

export function QueueChip({ state }) {
  const u = useUi();
  const [label, tone] = CHIP[state] || [state || "Unknown", "bg-gray-600 text-white"];
  return <span className={`text-[10px] px-2 py-0.5 font-bold ${u.brutalist ? "border-2 border-[#111] text-[#111] bg-[#FFE9A8] font-mono" : `rounded-full ${tone}`}`}>{label}</span>;
}

function SetupHint({ setup }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(setup.snippet); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* clipboard blocked: the text is selectable */ }
  };
  return (
    <div className="space-y-2 text-xs">
      <div className="flex gap-2 items-start text-amber-400"><Info size={14} className="shrink-0 mt-0.5" />
        <span>The print queue is not enabled in Moonraker. Add this section to <b className="font-mono">{setup.file}</b> and restart Moonraker:</span></div>
      <pre className="p-2 bg-black/30 rounded font-mono text-[11px] overflow-auto select-all">{setup.snippet}</pre>
      <Btn onClick={copy}><Copy size={12} /> {copied ? "Copied" : "Copy snippet"}</Btn>
    </div>
  );
}

// The print queue: jobs in order (drag to reorder), totals and an ETA, start/pause, multiply and remove.
// It polls the status only while mounted (the queue tab or the dashboard card).
export function QueuePanel({ compact = false }) {
  const u = useUi();
  const q = useStore((s) => s.queue);
  const thumbs = useStore((s) => s.fmThumbs);
  const subscribe = useStore((s) => s.subscribeQueue);
  const fetchQueue = useStore((s) => s.fetchQueue);
  const thumbsFor = useStore((s) => s.fmThumbsFor);
  const { queueStart, queuePause, queueRemove, queueClear, queueJump, queueAdd, queueReorder } = useStore.getState();
  const [selected, setSelected] = useState(() => new Set());
  const [dragFrom, setDragFrom] = useState(null);
  const [dragOver, setDragOver] = useState(null);
  const [msg, setMsg] = useState(null);
  const msgTimer = useRef(null);

  useEffect(() => subscribe(compact ? 8000 : 6000), [subscribe, compact]);
  useEffect(() => () => { if (msgTimer.current) clearTimeout(msgTimer.current); }, []);

  useEffect(() => {
    if (compact) return;
    const want = q.jobs.filter((j) => j.thumb).map((j) => ({ root: "gcodes", path: j.thumb }));
    if (want.length) thumbsFor(want);
  }, [q.jobs, compact, thumbsFor]);

  const say = (text, ok = true) => {
    setMsg({ text, ok });
    if (msgTimer.current) clearTimeout(msgTimer.current);
    msgTimer.current = setTimeout(() => setMsg(null), 5000);
  };
  const act = async (fn, okText) => { const r = await fn(); if (r.ok) { if (okText) say(okText); } else say(r.message, false); return r; };

  const jobs = q.jobs;
  const totals = q.totals;
  const printing = q.print?.busy;
  const ids = jobs.map((j) => j.id);

  const onDrop = (to) => {
    if (dragFrom == null || to == null || dragFrom === to) { setDragFrom(null); setDragOver(null); return; }
    const next = moveItem(ids, dragFrom, to);
    setDragFrom(null);
    setDragOver(null);
    act(() => queueReorder(next));
  };

  const toggle = (id) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const removeSelected = async () => { const r = await act(() => queueRemove([...selected]), "Removed"); if (r.ok) setSelected(new Set()); };

  if (!q.loaded) return <div className="p-3 text-xs opacity-60">Loading queue…</div>;
  if (!q.available && q.setup) return <div className="p-3"><SetupHint setup={q.setup} /></div>;
  if (q.error && !jobs.length) return <div className="p-3 text-xs text-red-400">{q.error}{q.unsupported ? "" : " — will retry"}</div>;

  const live = q.print?.busy ? q.print : null;
  return (
    <div className={`flex flex-col gap-2 min-h-0 ${compact ? "text-[11px]" : "text-xs"}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <QueueChip state={q.state} />
        <span className="opacity-70">{jobs.length} job{jobs.length === 1 ? "" : "s"}</span>
        {totals && jobs.length > 0 && (
          <span className="opacity-70" title={totals.finish_is_lower_bound ? "Some files have no time estimate: this is a minimum" : ""}>
            · {totals.finish_is_lower_bound ? "≥ " : ""}{formatDuration(totals.time_s) || "0m"}
            {formatFilament(totals.filament_mm, totals.filament_g) ? ` · ${formatFilament(totals.filament_mm, totals.filament_g)}` : ""}
            {totals.finish_ts ? ` · done ≈ ${formatClock(totals.finish_ts)}` : ""}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <Btn kind="primary" disabled={!jobs.length || printing} onClick={() => act(queueStart, "Starting the next job")}
            title={printing ? "A print is running; start the next job when it has finished" : "Load and start the first job"}><Play size={12} /> {compact ? "Start" : "Start next job"}</Btn>
          {q.state !== "paused" && <Btn onClick={() => act(queuePause, "Queue paused")} title="Do not load another job automatically"><Pause size={12} />{compact ? "" : " Pause"}</Btn>}
        </div>
      </div>

      {live && (
        <div className="px-2 py-1 bg-emerald-900/30 rounded flex items-center gap-2">
          <Layers size={12} /> <span className="truncate">Now printing <b className="font-mono">{live.filename}</b></span>
          {live.remaining_s ? <span className="ml-auto opacity-70 shrink-0">{formatDuration(live.remaining_s)} left</span> : null}
        </div>
      )}

      {q.manualStart && (
        <div className="flex gap-2 items-start opacity-70" role="note"><Info size={12} className="shrink-0 mt-0.5" /><span>{q.note}</span></div>
      )}
      {!q.manualStart && q.note && <div className="flex gap-2 items-start text-amber-400" role="note"><AlertTriangle size={12} className="shrink-0 mt-0.5" /><span>{q.note}</span></div>}
      {msg && <div role="status" className={msg.ok ? "text-emerald-400" : "text-red-400"}>{msg.text}</div>}

      {jobs.length === 0 ? (
        <div className="p-4 text-center opacity-50 italic">The queue is empty. Add files from the Files tab (right-click a G-code file, or select several).</div>
      ) : (
        <ul className="flex-1 min-h-0 overflow-auto divide-y divide-white/5" aria-label="Queued jobs">
          {jobs.map((j, i) => (
            <li key={j.id} draggable onDragStart={(e) => { setDragFrom(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", j.filename); }}
              onDragOver={(e) => { if (dragFrom != null) { e.preventDefault(); setDragOver(i); } }} onDrop={(e) => { e.preventDefault(); onDrop(i); }} onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
              className={`flex items-center gap-2 py-1.5 px-1 ${dragOver === i && dragFrom !== i ? "border-t-2 border-emerald-400" : ""} ${dragFrom === i ? "opacity-40" : ""}`}>
              <span className="cursor-grab opacity-40" aria-hidden="true"><GripVertical size={14} /></span>
              <input type="checkbox" checked={selected.has(j.id)} onChange={() => toggle(j.id)} aria-label={`Select ${j.filename}`} />
              <span className="w-5 text-right opacity-50">{i + 1}</span>
              {!compact && (
                <div className="w-9 h-9 shrink-0 bg-black/20 rounded overflow-hidden flex items-center justify-center">
                  {j.thumb && thumbs[`gcodes:${j.thumb}`] ? <img src={thumbs[`gcodes:${j.thumb}`]} alt="" className="w-full h-full object-cover" /> : <Layers size={14} className="opacity-30" />}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono" title={j.filename}>{j.filename}</div>
                <div className="opacity-60 flex gap-2 flex-wrap">
                  {j.has_meta ? (
                    <>
                      <span>{formatDuration(j.meta.estimated_time)}</span>
                      {formatFilament(j.meta.filament_total, j.meta.filament_weight_total) && <span>{formatFilament(j.meta.filament_total, j.meta.filament_weight_total)}</span>}
                      {j.eta_ts && <span>ends ≈ {formatClock(j.eta_ts)}</span>}
                    </>
                  ) : <span className="text-amber-400 flex items-center gap-1" title="Moonraker has no slicer metadata for this file, so it is left out of the totals and ETA"><AlertTriangle size={10} /> no metadata</span>}
                </div>
              </div>
              <Btn onClick={() => act(() => queueJump(j.id))} disabled={i === 0} title="Move to the front" aria-label={`Move ${j.filename} to the front`} className="!px-1.5"><ChevronsUp size={12} /></Btn>
              <Btn onClick={() => act(() => queueAdd([j.filename]), "Added another copy")} title="Add another copy at the end" aria-label={`Add another copy of ${j.filename}`} className="!px-1.5"><Plus size={12} /></Btn>
              <Btn onClick={() => act(() => queueRemove([j.id]))} title="Remove from the queue" aria-label={`Remove ${j.filename}`} className="!px-1.5"><Trash2 size={12} /></Btn>
            </li>
          ))}
        </ul>
      )}

      {jobs.length > 0 && (
        <div className="flex items-center gap-2">
          {selected.size > 0 && <Btn kind="danger" onClick={removeSelected}><Trash2 size={12} /> Remove {selected.size} selected</Btn>}
          <Btn className="ml-auto" onClick={() => { if (window.confirm("Remove every job from the queue?")) act(queueClear, "Queue cleared"); }}><Trash2 size={12} /> Clear all</Btn>
          <Btn onClick={fetchQueue} aria-label="Reload queue" className={u.brutalist ? "" : "!px-2"}>↻</Btn>
        </div>
      )}
    </div>
  );
}
