import React, { useEffect, useState } from "react";
import { Play, ListPlus, Flame, Download, Pencil, RefreshCw } from "lucide-react";
import { API, useStore } from "../store";
import { fileUrl } from "../slices/filesSlice";
import { fileKind, formatBytes, formatDuration, formatFilament, pickThumbnail, isEditable } from "./filesLogic";
import { Modal, Btn } from "./ui";
import { Markdown } from "./Markdown";
import { GcodePreview } from "./GcodePreview";

function TextBody({ root, path, markdown }) {
  const read = useStore((s) => s.fmReadText);
  const [state, setState] = useState({ loading: true, error: null, text: "" });
  useEffect(() => {
    let alive = true;
    read(root, path).then((r) => {
      if (!alive) return;
      setState(r.ok ? { loading: false, error: null, text: r.body.content } : { loading: false, error: r.message, text: "" });
    });
    return () => { alive = false; };
  }, [read, root, path]);
  if (state.loading) return <div className="text-xs opacity-60">Loading…</div>;
  if (state.error) return <div className="text-xs text-red-400">{state.error}</div>;
  if (markdown) return <Markdown text={state.text} />;
  return <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-[60vh] overflow-auto">{state.text.slice(0, 200000)}</pre>;
}

function MetaTable({ meta }) {
  const rows = [
    ["Slicer", [meta.slicer, meta.slicer_version].filter(Boolean).join(" ")],
    ["Filament", [meta.filament_type, meta.filament_name].filter(Boolean).join(" · ")],
    ["Usage", formatFilament(meta.filament_total, meta.filament_weight_total)],
    ["Nozzle / bed (first layer)", meta.first_layer_extr_temp != null || meta.first_layer_bed_temp != null
      ? `${meta.first_layer_extr_temp ?? "—"} / ${meta.first_layer_bed_temp ?? "—"} °C` : ""],
    ["Layer height", meta.layer_height != null ? `${meta.layer_height} mm` : ""],
    ["Object height", meta.object_height != null ? `${meta.object_height} mm` : ""],
    ["Estimated time", formatDuration(meta.estimated_time)],
    ["Last print", meta.print_start_time ? new Date(meta.print_start_time * 1000).toLocaleString() : ""],
  ].filter((r) => r[1]);
  if (!rows.length) return <div className="text-xs opacity-60 italic">No slicer metadata for this file yet. Use “Refresh metadata” to scan it.</div>;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v]) => (<React.Fragment key={k}><dt className="opacity-60">{k}</dt><dd className="font-mono">{v}</dd></React.Fragment>))}
    </dl>
  );
}

// Preview of one file in a dialog. ``actions`` carries the file manager's own handlers so this stays presentational.
export function FilePreview({ entry, root, actions, canPrint, canPreheat, onClose }) {
  const kind = fileKind(entry.name);
  const thumb = pickThumbnail(entry.meta?.thumbnails, 300);
  const thumbs = useStore((s) => s.fmThumbs);
  const thumbSrc = thumb ? (thumbs[`${root}:${thumb.path}`] || fileUrl(API, root, thumb.path, true)) : null;
  const footer = (
    <>
      {kind === "gcode" && <Btn kind="primary" disabled={!canPrint} onClick={() => actions.print(entry)} title={canPrint ? "" : "A print is already running"}><Play size={12} /> Print</Btn>}
      {kind === "gcode" && <Btn onClick={() => actions.queue([entry])}><ListPlus size={12} /> Add to queue</Btn>}
      {kind === "gcode" && <Btn disabled={!canPreheat} onClick={() => actions.preheat(entry)} title={canPreheat ? "" : "No temperatures in the metadata, or a print is running"}><Flame size={12} /> Preheat</Btn>}
      {kind === "gcode" && <Btn onClick={() => actions.refreshMeta(entry)}><RefreshCw size={12} /> Refresh metadata</Btn>}
      {isEditable(entry.name) && kind !== "gcode" && <Btn onClick={() => actions.edit(entry)}><Pencil size={12} /> Edit</Btn>}
      <Btn onClick={() => actions.download(entry)}><Download size={12} /> Download</Btn>
    </>
  );
  return (
    <Modal title={entry.name} onClose={onClose} wide footer={footer}>
      <div className="text-[11px] opacity-60 mb-3 font-mono">{root}/{entry.path} · {formatBytes(entry.size)}</div>
      {kind === "image" && <img src={fileUrl(API, root, entry.path, true)} alt={entry.name} className="max-w-full max-h-[70vh] mx-auto" />}
      {kind === "video" && <video src={fileUrl(API, root, entry.path, true)} controls className="max-w-full max-h-[70vh] mx-auto" />}
      {kind === "markdown" && <TextBody root={root} path={entry.path} markdown />}
      {kind === "text" && <TextBody root={root} path={entry.path} />}
      {kind === "gcode" && (
        <div className="grid md:grid-cols-[minmax(0,260px)_1fr] gap-4">
          <div className="space-y-3">
            {thumbSrc && <img src={thumbSrc} alt="" className="w-full max-w-[260px] bg-black/20 rounded" />}
            <MetaTable meta={entry.meta || {}} />
          </div>
          <div><div className="text-[10px] uppercase tracking-widest opacity-60 mb-1">Toolpath</div><GcodePreview root={root} path={entry.path} size={entry.size} /></div>
        </div>
      )}
      {(kind === "archive" || kind === "other") && <div className="text-xs opacity-60">No preview for this file type. Use Download.</div>}
    </Modal>
  );
}
