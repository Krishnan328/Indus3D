import React, { useRef, useState } from "react";
import { useDebouncedCallback } from "../utils/useDebouncedCallback";

// A slider that shows the printer's value, lets you drag freely, and sends ONE request once the value
// settles (debounced) or when you let go. The /api/v1/printer/adjust/* limit is 120 requests a minute, which a
// slider sending on every pixel would burn in seconds.
//
//   value     what Klipper reports now (shown when you are not dragging)
//   onCommit  called with the settled number; may be async
export function ToolheadSlider({ label, value, min, max, step = 1, format = (v) => String(v), onCommit, disabled, title, accent = "accent-blue-500", wait = 350 }) {
  const [local, setLocal] = useState(null);       // value while dragging / just after
  const release = useRef(null);
  const send = useDebouncedCallback(async (next) => {
    await onCommit(next);
    clearTimeout(release.current);
    release.current = setTimeout(() => setLocal(null), 1500);    // give the next status poll time to catch up
  }, wait);

  const shown = local ?? (Number.isFinite(value) ? value : min);
  return (
    <label className={`flex flex-col gap-0.5 text-[10px] ${disabled ? "opacity-40" : ""}`} title={title}>
      <span className="flex justify-between"><span className="uppercase tracking-widest opacity-70">{label}</span><span className="font-mono">{format(shown)}</span></span>
      <input type="range" min={min} max={max} step={step} value={shown} disabled={disabled} className={`w-full ${accent}`}
        onChange={(e) => { const v = Number(e.target.value); setLocal(v); send(v); }}
        onPointerUp={() => send.flush()} onKeyUp={() => send.flush()} onBlur={() => send.flush()} />
    </label>
  );
}
