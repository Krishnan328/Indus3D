import React, { useEffect, useState } from "react";
import { Files, Trash2, Play, Clock, Layers, RefreshCw } from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { formatDate } from "./dateFormat";

function formatBytes(n) {
  if (!n) return "0 KB";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  if (!seconds) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatWhen(unixSeconds, dateFormat) {
  if (!unixSeconds) return "";
  const d = new Date(unixSeconds * 1000);
  // Keep the original compact "Sep 2" style for the default browser format —
  // formatDate()'s non-browser formats are already compact (numeric), so
  // only this branch needs the short month/day override.
  if (!dateFormat || dateFormat === "browser") {
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return formatDate(d, dateFormat);
}

function FileRow({ file }) {
  const metadata       = useStore((s) => s.gcodeMetadata[file.path]);
  const fetchMetadata  = useStore((s) => s.fetchGcodeMetadata);
  const deleteFile     = useStore((s) => s.deleteGcodeFile);
  const startPrintFile = useStore((s) => s.startPrintFile);
  const dateFormat     = useStore((s) => s.uiPrefs.dateFormat);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const [busy, setBusy] = useState(false);

  useEffect(() => { fetchMetadata(file.path); }, [fetchMetadata, file.path]);

  const meta = (metadata && metadata !== "loading" && metadata !== "error") ? metadata : null;
  const thumb = meta?.thumbnails?.find((th) => th.width >= 100) ?? meta?.thumbnails?.[0];
  const thumbUrl = thumb
    ? `${API}/api/v1/printer/files/gcodes/${encodeURIComponent(
        (file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/") + 1) : "") + thumb.relative_path
      )}`
    : null;

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${file.path}"? This can't be undone.`)) return;
    setBusy(true);
    await deleteFile(file.path);
    setBusy(false);
  };

  const handlePrint = async () => {
    if (!window.confirm(`Start printing "${file.path}" now?`)) return;
    setBusy(true);
    await startPrintFile(file.path);
    setBusy(false);
  };

  return (
    <div className={`flex items-center gap-3 px-3 py-2 text-xs ${t.cell}`}>
      <div className={`w-10 h-10 shrink-0 flex items-center justify-center overflow-hidden ${brutalist ? "border-2 border-[#111]" : "rounded bg-black/10"}`}>
        {thumbUrl
          ? <img src={thumbUrl} alt="" className="w-full h-full object-cover" onError={(e) => { e.target.style.display = "none"; }} />
          : <Layers size={16} className="opacity-30" />}
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate font-mono">{file.path}</div>
        <div className="flex items-center gap-2 opacity-50 text-[10px] mt-0.5">
          <span>{formatBytes(file.size)}</span>
          <span>·</span>
          <span>{formatWhen(file.modified, dateFormat)}</span>
          {meta?.estimated_time && (
            <><span>·</span><span className="flex items-center gap-1"><Clock size={9} />{formatDuration(meta.estimated_time)}</span></>
          )}
          {meta?.filament_weight_total && (
            <><span>·</span><span>{meta.filament_weight_total.toFixed(0)}g</span></>
          )}
        </div>
      </div>

      <button onClick={handlePrint} disabled={busy} title="Print this file"
        className={`shrink-0 p-1.5 ${t.chip} ${brutalist ? "bg-[#B7E4C7]" : "bg-emerald-700 hover:bg-emerald-600 text-white"}`}>
        <Play size={12} />
      </button>
      <button onClick={handleDelete} disabled={busy} title="Delete"
        className={`shrink-0 p-1.5 ${t.chip} ${brutalist ? "bg-[#F4A6A0]" : "bg-red-800 hover:bg-red-700 text-white"}`}>
        <Trash2 size={12} />
      </button>
    </div>
  );
}

// ── File manager ─────────────────────────────────────────────────────────────
// Browse/print/delete gcode files already on the printer. Upload is handled
// separately by PrintStatusCard — this is for files that are already there.
// Metadata (thumbnail, print time, filament) is fetched per-row on mount;
// fine for typical gcode folder sizes, worth revisiting with pagination or
// lazy-on-scroll if someone has hundreds of files.
export function FileManager() {
  const files       = useStore((s) => s.gcodeFiles);
  const fetchFiles  = useStore((s) => s.fetchGcodeFiles);
  const t = useThemeTokens();
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    await fetchFiles();
    setLoading(false);
  };

  useEffect(() => { fetchFiles(); }, [fetchFiles]);

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-3">
      <div className={`flex items-center gap-2 px-4 py-3 ${t.panel}`}>
        <Files size={16} />
        <h2 className={t.heading}>Files ({files.length})</h2>
        <button onClick={refresh} disabled={loading} className="ml-auto opacity-60 hover:opacity-100">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5 pr-1">
        {!files.length
          ? <div className={`p-6 text-center text-xs opacity-40 italic ${t.panel}`}>
              No gcode files found on the printer.
            </div>
          : files.map((f) => <FileRow key={f.path} file={f} />)
        }
      </div>
    </div>
  );
}
