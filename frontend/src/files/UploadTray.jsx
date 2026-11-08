import React from "react";
import { X, Check, AlertTriangle, Loader2 } from "lucide-react";
import { useStore } from "../store";
import { formatBytes } from "./filesLogic";
import { Btn } from "./ui";
import { useUi } from "./useUi";

// Floating list of uploads with a progress bar each (XMLHttpRequest progress events). A name collision asks
// before overwriting; nothing is replaced silently.
export function UploadTray() {
  const u = useUi();
  const uploads = useStore((s) => s.fmUploads);
  const resolve = useStore((s) => s.fmUploadResolve);
  const cancel = useStore((s) => s.fmUploadCancel);
  const clear = useStore((s) => s.fmUploadsClear);
  if (!uploads.length) return null;
  const active = uploads.filter((x) => x.status === "uploading" || x.status === "queued");
  const total = uploads.reduce((a, x) => a + x.size, 0) || 1;
  const done = uploads.reduce((a, x) => a + (x.status === "done" ? x.size : x.loaded || 0), 0);
  return (
    <div className={`fixed bottom-4 right-4 z-[70] w-80 max-w-[92vw] text-xs ${u.t.panelSolid}`} aria-live="polite">
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${u.t.border}`}>
        <span className="font-bold">{active.length ? `Uploading ${active.length} file${active.length > 1 ? "s" : ""}` : "Uploads"}</span>
        <span className="opacity-50">{Math.round((100 * done) / total)}%</span>
        <button type="button" onClick={clear} aria-label="Clear finished uploads" className="ml-auto opacity-60 hover:opacity-100"><X size={14} /></button>
      </div>
      <ul className="max-h-60 overflow-auto divide-y divide-white/5">
        {uploads.map((x) => (
          <li key={x.id} className="px-3 py-2">
            <div className="flex items-center gap-2">
              {x.status === "uploading" && <Loader2 size={12} className="animate-spin shrink-0" />}
              {x.status === "done" && <Check size={12} className="text-emerald-500 shrink-0" />}
              {(x.status === "error" || x.status === "exists") && <AlertTriangle size={12} className="text-amber-500 shrink-0" />}
              <span className="truncate flex-1 font-mono" title={x.name}>{x.name}</span>
              <span className="opacity-50 shrink-0">{formatBytes(x.size)}</span>
              {(x.status === "uploading" || x.status === "queued") && (
                <button type="button" onClick={() => cancel(x.id)} aria-label={`Cancel ${x.name}`} className="opacity-60 hover:opacity-100"><X size={12} /></button>
              )}
            </div>
            {(x.status === "uploading" || x.status === "queued") && (
              <div className="mt-1 h-1.5 bg-black/20 overflow-hidden" role="progressbar" aria-valuenow={Math.round((100 * (x.loaded || 0)) / (x.size || 1))} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full bg-emerald-500 transition-[width]" style={{ width: `${x.status === "queued" ? 0 : Math.min(100, (100 * (x.loaded || 0)) / (x.size || 1))}%` }} />
              </div>
            )}
            {x.status === "exists" && (
              <div className="mt-1.5 flex items-center gap-2">
                <span className="opacity-70 flex-1">Already exists.</span>
                <Btn onClick={() => resolve(x.id, "overwrite")}>Overwrite</Btn>
                <Btn onClick={() => resolve(x.id, "skip")}>Skip</Btn>
              </div>
            )}
            {x.status === "error" && <div className="mt-1 text-red-400">{x.error}</div>}
            {x.status === "canceled" && <div className="mt-1 opacity-50">Skipped</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}
