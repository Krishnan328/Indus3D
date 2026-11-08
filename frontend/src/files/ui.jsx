import React, { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useUi } from "./useUi";

// Small shared pieces for the file manager, queue and editor so every surface follows the active theme.

export function Btn({ kind = "plain", className = "", children, ...rest }) {
  const u = useUi();
  const tone = kind === "primary" ? u.primary : kind === "danger" ? u.danger : u.btn;
  return (
    <button type="button" {...rest}
      className={`inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 text-xs transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${tone} ${className}`}>
      {children}
    </button>
  );
}

export function Modal({ title, onClose, children, wide = false, footer = null, labelledBy = "modal-title" }) {
  const u = useUi();
  const ref = useRef(null);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/60" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={labelledBy}
        className={`flex flex-col max-h-[90vh] w-full ${wide ? "max-w-5xl" : "max-w-md"} outline-none ${u.t.panelSolid}`}>
        <div className={`flex items-center gap-2 px-4 py-3 border-b ${u.t.border}`}>
          <h3 id={labelledBy} className={`${u.t.heading} truncate normal-case`}>{title}</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="ml-auto opacity-60 hover:opacity-100"><X size={16} /></button>
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-4 text-sm">{children}</div>
        {footer && <div className={`flex items-center justify-end gap-2 px-4 py-3 border-t ${u.t.border}`}>{footer}</div>}
      </div>
    </div>
  );
}

export function Toast({ toast, onClose }) {
  const u = useUi();
  useEffect(() => {
    if (!toast) return undefined;
    const id = setTimeout(onClose, toast.ms || 5000);
    return () => clearTimeout(id);
  }, [toast, onClose]);
  if (!toast) return null;
  const tone = toast.ok === false ? (u.brutalist ? "bg-[#F4A6A0] text-[#111]" : "bg-red-900/90 text-red-100 border border-red-700")
    : (u.brutalist ? "bg-[#B7E4C7] text-[#111]" : "bg-emerald-900/90 text-emerald-100 border border-emerald-700");
  return (
    <div role="status" className={`fixed bottom-5 left-1/2 -translate-x-1/2 z-[90] px-4 py-2 text-xs max-w-[90vw] flex items-center gap-3 ${u.brutalist ? "border-2 border-[#111]" : "rounded-lg"} ${tone}`}>
      <span>{toast.message}</span>
      {toast.action && <button type="button" onClick={toast.action.run} className="underline font-bold">{toast.action.label}</button>}
    </div>
  );
}
