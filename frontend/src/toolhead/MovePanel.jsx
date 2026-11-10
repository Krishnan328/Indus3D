import React, { useMemo } from "react";
import { sectorPath } from "../slices/toolheadLogic";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, ChevronsUp, ChevronsDown, Home } from "lucide-react";

// Jog controls in three styles (Settings -> Control -> Toolhead style): "bars" (a row of buttons per axis),
// "cross" (arrow pad) and "circle" (a wheel whose rings are the move distances).

const fmtDistance = (d) => String(Number(d.toFixed(3)));

function Bars({ distances, jog, disabled, btn }) {
  return (
    <div className="flex flex-col gap-1.5">
      {["x", "y", "z"].map((axis) => (
        <div key={axis} className="flex items-center gap-1">
          <span className="w-4 text-[10px] font-bold uppercase opacity-70">{axis}</span>
          {[...distances].reverse().map((d) => <button key={`-${d}`} className={`${btn} flex-1 px-1 text-[10px]`} disabled={disabled} onClick={() => jog(axis, -d)}>−{fmtDistance(d)}</button>)}
          <span className="w-px self-stretch bg-current opacity-20" />
          {distances.map((d) => <button key={`+${d}`} className={`${btn} flex-1 px-1 text-[10px]`} disabled={disabled} onClick={() => jog(axis, d)}>+{fmtDistance(d)}</button>)}
        </div>
      ))}
    </div>
  );
}

function Cross({ step, jog, disabled, btn }) {
  return (
    <div className="grid grid-cols-[1fr_1fr] gap-4 items-center">
      <div className="grid grid-cols-3 gap-1">
        <span /><button className={btn} disabled={disabled} onClick={() => jog("y", step)} aria-label="Y plus"><ArrowUp size={15} /></button><span />
        <button className={btn} disabled={disabled} onClick={() => jog("x", -step)} aria-label="X minus"><ArrowLeft size={15} /></button>
        <div className="flex items-center justify-center text-[9px] opacity-50">XY</div>
        <button className={btn} disabled={disabled} onClick={() => jog("x", step)} aria-label="X plus"><ArrowRight size={15} /></button>
        <span /><button className={btn} disabled={disabled} onClick={() => jog("y", -step)} aria-label="Y minus"><ArrowDown size={15} /></button><span />
      </div>
      <ZColumn step={step} jog={jog} disabled={disabled} btn={btn} />
    </div>
  );
}

function ZColumn({ step, jog, disabled, btn }) {
  return (
    <div className="grid grid-cols-2 gap-1 items-center">
      <button className={btn} disabled={disabled} onClick={() => jog("z", step)}><ChevronsUp size={16} /><span className="ml-1 text-[10px]">Z+</span></button>
      <button className={btn} disabled={disabled} onClick={() => jog("z", -step)}><ChevronsDown size={16} /><span className="ml-1 text-[10px]">Z−</span></button>
    </div>
  );
}

function Circle({ distances, step, setStep, jog, disabled, btn, onHomeXY }) {
  const rings = distances.slice(-4);                      // innermost = smallest
  const hub = 20; const R = 72; const band = (R - hub) / rings.length;
  const dirs = [{ mid: 0, axis: "y", sign: 1 }, { mid: 90, axis: "x", sign: 1 }, { mid: 180, axis: "y", sign: -1 }, { mid: 270, axis: "x", sign: -1 }];
  return (
    <div className="grid grid-cols-[auto_1fr] gap-4 items-center">
      <svg viewBox="-76 -76 152 152" className="w-36 h-36" role="group" aria-label="XY wheel">
        {rings.map((d, i) => dirs.map((dir) => (
          <path key={`${d}${dir.mid}`} d={sectorPath(0, 0, hub + i * band, hub + (i + 1) * band - 1, dir.mid)}
            className={`${disabled ? "opacity-30" : "cursor-pointer hover:opacity-80"}`} style={{ fill: `rgba(59,130,246,${0.18 + i * 0.14})` }}
            onClick={() => !disabled && jog(dir.axis, dir.sign * d)}>
            <title>{`${dir.axis.toUpperCase()}${dir.sign > 0 ? "+" : "−"}${fmtDistance(d)} mm`}</title>
          </path>
        )))}
        <circle r={hub - 2} className={`fill-emerald-600 ${disabled ? "opacity-30" : "cursor-pointer hover:opacity-80"}`} onClick={() => !disabled && onHomeXY()}><title>Home XY</title></circle>
        <Home x={-7} y={-7} width={14} height={14} className="text-white pointer-events-none" />
      </svg>
      <div className="flex flex-col gap-2">
        <ZColumn step={step} jog={jog} disabled={disabled} btn={btn} />
        <div className="flex flex-wrap gap-1">
          {distances.map((d) => <button key={d} className={`${btn} px-2 text-[10px] ${step === d ? "bg-blue-600 text-white" : ""}`} onClick={() => setStep(d)}>Z {fmtDistance(d)}</button>)}
        </div>
      </div>
    </div>
  );
}

export function MovePanel({ style, distances, step, setStep, jog, disabled, btn, onHomeXY }) {
  const sorted = useMemo(() => [...distances].sort((a, b) => a - b), [distances]);
  if (style === "bars") return <Bars distances={sorted} jog={jog} disabled={disabled} btn={btn} />;
  if (style === "circle") return <Circle distances={sorted} step={step} setStep={setStep} jog={jog} disabled={disabled} btn={btn} onHomeXY={onHomeXY} />;
  return <Cross step={step} jog={jog} disabled={disabled} btn={btn} />;
}
