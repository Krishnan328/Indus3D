import React, { useCallback, useEffect, useState } from "react";
import { Save, RotateCw, X, AlertTriangle, Lock } from "lucide-react";
import { API, useStore } from "../store";
import { modeForFile } from "./syntax";
import { Btn } from "../files/ui";
import { useUi } from "../files/useUi";

const EditorPane = React.lazy(() => import("./EditorPane"));

// Edit any text file of a Moonraker root in a full-screen dialog. Used by the file manager; reads and writes
// through /api/v1/files/text (modified-time conflict check, read-only roots, config locked during a print).
export default function EditorModal({ root, path, writable, onClose }) {
  const u = useUi();
  const read = useStore((s) => s.fmReadText);
  const write = useStore((s) => s.fmWriteText);
  const [state, setState] = useState({ phase: "loading", error: null, modified: null, locked: false, lossy: false });
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const mode = modeForFile(path);
  const dirty = text !== saved;
  const klipperCfg = root === "config" && mode === "klipper";
  const readOnly = !writable || state.locked || state.lossy;

  useEffect(() => {
    let alive = true;
    read(root, path).then((r) => {
      if (!alive) return;
      if (r.ok) {
        setText(r.body.content);
        setSaved(r.body.content);
        setState({ phase: "ready", error: null, modified: r.body.modified, locked: !!r.body.locked, lossy: !!r.body.lossy });
      } else {
        setState({ phase: "error", error: r.message, modified: null, locked: false, lossy: false });
      }
    });
    return () => { alive = false; };
  }, [read, root, path]);

  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const requestClose = useCallback(() => {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    onClose();
  }, [dirty, onClose]);

  const save = useCallback(async (restart = null) => {
    if (readOnly || busy) return false;
    setBusy(true);
    setMsg(null);
    let r = await write(root, path, text, state.modified);
    if (!r.ok && r.body?.code === "conflict") {
      if (window.confirm("This file was changed on the printer after you opened it. Overwrite it with your version?")) {
        r = await write(root, path, text, state.modified, true);
      }
    }
    if (r.ok) {
      setSaved(text);
      setState((s) => ({ ...s, modified: r.body.modified ?? s.modified }));
      setMsg({ ok: true, text: "Saved" });
      if (restart) {
        try {
          const res = await fetch(`${API}/api/v1/printer/${restart}`, { method: "POST" });
          setMsg(res.ok ? { ok: true, text: "Saved, restarting Klipper" } : { ok: false, text: "Saved, but the restart failed" });
        } catch { setMsg({ ok: false, text: "Saved, but the restart failed" }); }
      }
    } else {
      setMsg({ ok: false, text: r.message });
    }
    setBusy(false);
    return r.ok;
  }, [readOnly, busy, write, root, path, text, state.modified]);

  return (
    <div className="fixed inset-0 z-[80] flex flex-col bg-black/70 p-3 sm:p-8" onMouseDown={(e) => { if (e.target === e.currentTarget) requestClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={`Editor: ${path}`} className={`flex-1 min-h-0 flex flex-col ${u.t.panelSolid}`}>
        <div className={`flex items-center gap-2 px-4 py-2 border-b ${u.t.border} flex-wrap`}>
          <h3 className={`${u.t.heading} truncate normal-case`}>{path}</h3>
          <span className="text-[10px] opacity-50 font-mono">{root}</span>
          {dirty && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-500 font-bold">UNSAVED</span>}
          {readOnly && <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-400 font-bold flex items-center gap-1"><Lock size={10} /> READ-ONLY</span>}
          {msg && <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${msg.ok ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`} role="status">{msg.text}</span>}
          <div className="ml-auto flex items-center gap-2">
            {!readOnly && <Btn kind="primary" disabled={busy || !dirty} onClick={() => save()}><Save size={12} /> Save</Btn>}
            {!readOnly && klipperCfg && <Btn disabled={busy} onClick={() => save("restart")} title="Save, then RESTART Klipper"><RotateCw size={12} /> Save &amp; restart</Btn>}
            {!readOnly && klipperCfg && <Btn disabled={busy} onClick={() => save("firmware_restart")} title="Save, then FIRMWARE_RESTART (reloads the MCU too)">Save &amp; firmware restart</Btn>}
            <button type="button" onClick={requestClose} aria-label="Close editor" className="p-1 opacity-70 hover:opacity-100"><X size={18} /></button>
          </div>
        </div>
        {state.locked && <div className="px-4 py-1.5 text-xs bg-sky-900/40 text-sky-100">A print is running: the configuration can be read but not changed until it finishes.</div>}
        {state.lossy && <div className="px-4 py-1.5 text-xs bg-amber-900/40 text-amber-100 flex items-center gap-2"><AlertTriangle size={12} /> This file is not valid UTF-8, so it is shown read-only to avoid corrupting it.</div>}
        <div className="flex-1 min-h-0">
          {state.phase === "loading" && <div className="p-6 text-sm opacity-60">Loading {path}…</div>}
          {state.phase === "error" && <div className="p-6 text-sm text-red-400">{state.error}</div>}
          {state.phase === "ready" && (
            <React.Suspense fallback={<div className="p-6 text-sm opacity-60">Loading editor…</div>}>
              <EditorPane key={`${root}/${path}`} value={text} mode={mode} readOnly={readOnly} onChange={setText}
                onSave={() => save()} onSaveRestart={klipperCfg ? () => save("restart") : undefined} onEscape={requestClose} />
            </React.Suspense>
          )}
        </div>
      </div>
    </div>
  );
}
