import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Modal, Btn } from "./ui";
import { useUi } from "./useUi";
import { validateName } from "./filesLogic";

// Rename / new folder: one text field with the same name rules as the server.
export function NameDialog({ title, label, initial = "", confirmLabel = "OK", onSubmit, onClose }) {
  const u = useUi();
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const dot = initial.lastIndexOf(".");
    el.setSelectionRange(0, dot > 0 ? dot : initial.length);       // select the stem, keep the extension
  }, [initial]);
  const invalid = validateName(value);
  const submit = async (e) => {
    e?.preventDefault();
    if (invalid || busy) return;
    setBusy(true);
    const err = await onSubmit(value);
    if (err) { setError(err); setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" disabled={!!invalid || busy || value === initial} onClick={submit}>{confirmLabel}</Btn></>}>
      <form onSubmit={submit} className="space-y-2">
        <label className="block text-xs opacity-70" htmlFor="name-dialog-input">{label}</label>
        <input id="name-dialog-input" ref={ref} value={value} onChange={(e) => { setValue(e.target.value); setError(null); }}
          className={`w-full px-2 py-1.5 text-sm font-mono outline-none ${u.input}`} spellCheck={false} aria-invalid={!!invalid} />
        <div className="text-xs text-red-400 min-h-[1rem]" role="alert">{error || (value !== initial && invalid) || ""}</div>
      </form>
    </Modal>
  );
}

export function ConfirmDialog({ title, children, confirmLabel = "OK", danger = false, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn>
        <Btn kind={danger ? "danger" : "primary"} disabled={busy} onClick={async () => { setBusy(true); await onConfirm(); }}>{confirmLabel}</Btn></>}>
      <div className="space-y-2 text-xs">{children}</div>
    </Modal>
  );
}

export function NameList({ names, max = 8 }) {
  return (
    <ul className="font-mono max-h-40 overflow-auto bg-black/20 rounded p-2">
      {names.slice(0, max).map((n) => <li key={n} className="truncate">{n}</li>)}
      {names.length > max && <li className="opacity-60">… and {names.length - max} more</li>}
    </ul>
  );
}

export function WarnLine({ children }) {
  return <div className="flex gap-2 items-start text-amber-400"><AlertTriangle size={14} className="shrink-0 mt-0.5" /><span>{children}</span></div>;
}

// Add to queue: how many copies ("multiply") and where.
export function QueueAddDialog({ names, onSubmit, onClose }) {
  const u = useUi();
  const [repeat, setRepeat] = useState(1);
  const [front, setFront] = useState(false);
  const [busy, setBusy] = useState(false);
  const n = Math.max(1, Math.min(50, Number(repeat) || 1));
  return (
    <Modal title="Add to print queue" onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn>
        <Btn kind="primary" disabled={busy} onClick={async () => { setBusy(true); await onSubmit({ repeat: n, position: front ? "front" : "end" }); }}>
          Add {names.length * n} job{names.length * n > 1 ? "s" : ""}</Btn></>}>
      <div className="space-y-3 text-xs">
        <NameList names={names} />
        <label className="flex items-center gap-2">Copies of each file
          <input type="number" min={1} max={50} value={repeat} onChange={(e) => setRepeat(e.target.value)} className={`w-16 px-2 py-1 ${u.input}`} /></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={front} onChange={(e) => setFront(e.target.checked)} /> Put at the front of the queue</label>
        <p className="opacity-60">Jobs are not started automatically: after a print finishes, check the bed is clear and press Start on the queue.</p>
      </div>
    </Modal>
  );
}
