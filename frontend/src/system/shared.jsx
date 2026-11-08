import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, Copy, Check, Loader2 } from "lucide-react";
import { useThemeTokens } from "../theme";

// Pieces shared by the System page panels.

export function Btn({ children, onClick, disabled, danger, title, small = true, className = "" }) {
  const t = useThemeTokens();
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title}
      className={`${small ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm"} border rounded inline-flex items-center gap-1 transition-colors
        disabled:opacity-40 disabled:cursor-not-allowed ${danger ? "border-red-500/60 text-red-500 hover:bg-red-500/10" : `${t.border} hover:bg-gray-500/10`} ${className}`}>
      {children}
    </button>
  );
}

export function Stat({ label, value, tone = "", sub }) {
  const t = useThemeTokens();
  return (
    <div className={`p-2 ${t.cell}`}>
      <span className={t.label}>{label}</span>
      <span className={`font-mono text-sm break-words ${tone}`}>{value ?? "—"}</span>
      {sub ? <span className="block text-[10px] opacity-60 mt-0.5">{sub}</span> : null}
    </div>
  );
}

export function Card({ title, right, children }) {
  const t = useThemeTokens();
  return (
    <section className={`p-4 ${t.panel}`}>
      {(title || right) && (
        <div className="flex items-center gap-2 mb-3">
          {title && <h3 className={t.heading}>{title}</h3>}
          <div className="ml-auto flex items-center gap-2">{right}</div>
        </div>
      )}
      {children}
    </section>
  );
}

// Renders its children once the resource has data; otherwise says why not ("not available on this Moonraker",
// the error, or loading). `data` stays visible across a failed refresh, with a small warning above it.
export function Resource({ res, children, what = "This" }) {
  const t = useThemeTokens();
  if (!res || !res.loaded) {
    return <div className={`p-3 text-xs opacity-60 flex items-center gap-2 ${t.cell}`}><Loader2 size={13} className="animate-spin" />Loading...</div>;
  }
  if (res.unsupported) {
    return <div className={`p-3 text-xs ${t.cell}`} role="status"><b>Not available on this Moonraker.</b> <span className="opacity-70">{what} needs an endpoint your Moonraker version does not have ({res.error}).</span></div>;
  }
  if (!res.data) {
    return <div className="p-3 text-xs rounded border border-red-500/50 bg-red-500/10 text-red-400" role="alert">{res.error || "Unavailable"}</div>;
  }
  return (
    <>
      {!res.ok && <div className="mb-2 p-2 text-xs rounded border border-amber-500/50 bg-amber-500/10 text-amber-500" role="alert">Showing the last good reading: {res.error}</div>}
      {children(res.data)}
    </>
  );
}

// Modal confirmation. `extra` is an optional checkbox ({label}) that must be ticked to enable the confirm button.
export function ConfirmDialog({ title, body, confirmLabel = "Confirm", danger, extra, onConfirm, onCancel }) {
  const t = useThemeTokens();
  const [ticked, setTicked] = useState(false);
  const cancelRef = useRef(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" role="presentation">
      <div role="alertdialog" aria-modal="true" aria-label={title} className={`w-full max-w-md p-5 ${t.panelSolid}`}>
        <h3 className={`${t.heading} flex items-center gap-2 mb-3 ${danger ? "text-red-500" : ""}`}>
          {danger && <AlertTriangle size={16} />}{title}
        </h3>
        <div className="text-sm opacity-80 mb-4 space-y-2">{body}</div>
        {extra && (
          <label className="flex items-start gap-2 text-xs mb-4 text-red-500">
            <input type="checkbox" className="mt-0.5" checked={ticked} onChange={(e) => setTicked(e.target.checked)} />
            <span>{extra.label}</span>
          </label>
        )}
        <div className="flex justify-end gap-2">
          <button ref={cancelRef} type="button" onClick={onCancel} className={`px-3 py-1.5 text-sm border rounded ${t.border} hover:bg-gray-500/10`}>Cancel</button>
          <button type="button" disabled={!!extra && !ticked} onClick={() => onConfirm({ extra: ticked })}
            className={`px-3 py-1.5 text-sm rounded text-white disabled:opacity-40 ${danger ? "bg-red-600 hover:bg-red-500" : "bg-blue-600 hover:bg-blue-500"}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
      }
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch { /* clipboard blocked: the path is selectable text next to the button */ }
  };
  return <Btn onClick={copy} title={`Copy ${text}`}>{done ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}{done ? "Copied" : label}</Btn>;
}
