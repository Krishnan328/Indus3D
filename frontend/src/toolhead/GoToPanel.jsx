import React, { useState } from "react";
import { MoveRight, RefreshCw } from "lucide-react";
import { useStore } from "../store";

// Typed absolute move (POST /api/v1/control/move; refused during a print by the backend) and the endstop
// state (QUERY_ENDSTOPS). Ported from the host build's toolhead card.
export function GoToPanel({ btn, connected, printing, x, y, z }) {
  const moveToolhead = useStore((s) => s.moveToolhead);
  const queryEndstops = useStore((s) => s.queryEndstops);
  const endstops = useStore((s) => s.endstopsState);
  const speed = useStore((s) => s.uiPrefs.toolheadSpeedXY) || 100;
  const [target, setTarget] = useState({ x: "", y: "", z: "" });
  const [message, setMessage] = useState("");
  const blocked = !connected || printing;
  const field = (axis, current, digits) => (
    <label className="flex flex-col gap-0.5 text-[9px] uppercase tracking-widest opacity-70">{axis}
      <input type="number" step="any" inputMode="decimal" value={target[axis.toLowerCase()]} disabled={blocked}
        placeholder={Number(current).toFixed(digits)} aria-label={`Target ${axis} position in millimetres`}
        onChange={(e) => setTarget({ ...target, [axis.toLowerCase()]: e.target.value })}
        className="px-1 py-1 rounded border border-gray-500/30 bg-transparent font-mono text-xs normal-case tracking-normal" />
    </label>
  );
  const go = async () => {
    const coords = Object.fromEntries(Object.entries(target).filter(([, v]) => v !== "" && Number.isFinite(Number(v))).map(([k, v]) => [k, Number(v)]));
    if (!Object.keys(coords).length) { setMessage("Enter at least one coordinate"); return; }
    const res = await moveToolhead(coords, speed * 60);
    setMessage(res?.error || "Move sent");
  };
  const entries = endstops && typeof endstops === "object" ? Object.entries(endstops) : [];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">{field("X", x, 1)}{field("Y", y, 1)}{field("Z", z, 2)}</div>
      <button className={`${btn} text-[10px] gap-1`} disabled={blocked} onClick={go}
        title={printing ? "Disabled while a print is active" : "Move the toolhead to the typed coordinates"}><MoveRight size={12} />Go to position</button>
      <div className="flex items-center justify-between pt-1">
        <span className="text-[9px] uppercase tracking-widest opacity-60">Endstops</span>
        <button className={`${btn} text-[10px] gap-1 px-2`} disabled={!connected} onClick={queryEndstops}><RefreshCw size={11} />Query</button>
      </div>
      {entries.length > 0 && (
        <div className="grid grid-cols-3 gap-1 text-[10px] font-mono">
          {entries.map(([name, state]) => (
            <div key={name} className="px-1.5 py-1 rounded border border-gray-500/20 flex justify-between">
              <span className="uppercase opacity-70">{name.replace("stepper_", "")}</span>
              <span className={String(state).toLowerCase().includes("trigger") ? "text-amber-400" : "text-emerald-500"}>{String(state)}</span>
            </div>
          ))}
        </div>
      )}
      {message && <div className="text-[10px] opacity-70" role="status">{message}</div>}
    </div>
  );
}
