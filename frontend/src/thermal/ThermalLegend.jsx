import React from "react";
import { formatReading } from "../slices/thermalLogic";

// Legend chips for the temperature chart: click = hide / show, hover = highlight the line in the plot,
// the dot opens a colour picker. Targets, power and fan overlays follow their parent series.
export function ThermalLegend({ items, hidden, onToggle, onFocus, onColor, focusId, t }) {
  return (
    <div className="flex flex-wrap gap-1.5 mb-2 max-h-[4.5rem] overflow-y-auto" role="group" aria-label="Chart series">
      {items.map(({ def, color, value, target }) => {
        const off = !!hidden[def.id];
        return (
          <div key={def.id} onMouseEnter={() => onFocus(def.id)} onMouseLeave={() => onFocus(null)}
            className={`flex items-center gap-1.5 pl-1.5 pr-2 py-1 text-[10px] ${t.cell} ${off ? "opacity-40" : ""} ${focusId === def.id ? "ring-1 ring-blue-400" : ""}`}>
            <label className="relative w-3 h-3 shrink-0 cursor-pointer" title="Change colour">
              <i className="block w-3 h-3 rounded-full" style={{ background: color }} />
              <input type="color" value={/^#[0-9a-f]{6}$/i.test(color) ? color : "#888888"} aria-label={`${def.label} colour`}
                onChange={(e) => onColor(def.id, e.target.value)} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" />
            </label>
            <button type="button" onClick={() => onToggle(def.id)} aria-pressed={!off} title={off ? "Show" : "Hide"}
              className="flex items-baseline gap-1.5 text-left">
              <span className="font-bold">{def.label}</span>
              <span className="font-mono opacity-80">{off ? "hidden" : formatReading(value, target)}</span>
            </button>
          </div>
        );
      })}
    </div>
  );
}
