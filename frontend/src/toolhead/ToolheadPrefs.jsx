import React, { useState } from "react";
import { cleanIncrements, parseNumberList } from "../slices/toolheadLogic";

// Settings -> Control: toolhead layout and extrusion / Z-offset presets, stored in uiPrefs.
// Rendered inside ControlTab (SettingsModal.jsx) with the same props the other fields there get.
const STYLES = [["bars", "Bars"], ["circle", "Circle"], ["cross", "Cross"]];

function ListField({ label, hint, value, onCommit, parse, borderClass, brutalist }) {
  const [text, setText] = useState(null);                       // null = show the stored value
  const shown = text ?? (value || []).join(", ");
  const commit = () => {
    if (text == null) return;
    const parsed = parse(text);
    if (parsed.length) onCommit(parsed);
    setText(null);
  };
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="opacity-60">{label}</span>
      <input type="text" value={shown} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
      <span className="opacity-50">{hint}</span>
    </label>
  );
}

export function ToolheadPrefs({ uiPrefs, setUiPref, borderClass, brutalist, t, toggle }) {
  const Switch = toggle;
  const active = (on) => `flex-1 px-4 py-2 text-xs font-bold transition-all ${borderClass} ${on ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "rounded bg-gray-500/10")}`;
  return (
    <>
      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Toolhead Layout</h4>
        <div className="flex gap-2 mb-3" role="radiogroup" aria-label="Toolhead style">
          {STYLES.map(([id, label]) => <button key={id} role="radio" aria-checked={uiPrefs.toolheadStyle === id} onClick={() => setUiPref("toolheadStyle", id)} className={active(uiPrefs.toolheadStyle === id)}>{label}</button>)}
        </div>
        <div className="flex flex-col gap-2">
          <Switch label="Combined XY homing" description="One XY home button instead of separate X and Y buttons."
            checked={uiPrefs.combinedXYHome} onChange={(v) => setUiPref("combinedXYHome", v)} borderClass={borderClass} brutalist={brutalist} />
          <Switch label="Hide axis controls during a print" description="Replaces the jog pad with a note while printing (it is disabled then anyway)."
            checked={uiPrefs.hideAxisControlsInPrint} onChange={(v) => setUiPref("hideAxisControlsInPrint", v)} borderClass={borderClass} brutalist={brutalist} />
        </div>
      </div>
      <div className={`pt-6 flex flex-col gap-3 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`${t.label}`}>Extrusion and Z Offset</h4>
        <ListField label="Extrude / retract amounts (mm)" hint="Comma-separated, up to 100 mm each." value={uiPrefs.extrudeAmounts}
          parse={(s) => parseNumberList(s, { min: 0, max: 100 })} onCommit={(v) => setUiPref("extrudeAmounts", v)} borderClass={borderClass} brutalist={brutalist} />
        <ListField label="Extrusion speeds (mm/s)" hint="Comma-separated, 0.5 to 50 mm/s." value={uiPrefs.extrudeSpeeds}
          parse={(s) => parseNumberList(s, { min: 0.5, max: 50 })} onCommit={(v) => setUiPref("extrudeSpeeds", v)} borderClass={borderClass} brutalist={brutalist} />
        <ListField label="Z-offset increments (mm)" hint="Babystep sizes, each up to 0.5 mm."
          value={cleanIncrements(uiPrefs.zOffsetSteps, [0.01, 0.025, 0.05, 0.1])}
          parse={(s) => cleanIncrements(parseNumberList(s, { min: 0, max: 0.5 }), [])} onCommit={(v) => setUiPref("zOffsetSteps", v)} borderClass={borderClass} brutalist={brutalist} />
      </div>
    </>
  );
}
