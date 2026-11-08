import React from "react";
import { useStore } from "../store";
import { levelingActions, reasonDisabled } from "../slices/toolheadLogic";

// Leveling / probing buttons for what this printer has, the manual-probe dialog (TESTZ / ACCEPT / ABORT)
// when Klipper has one open, and motors off. Disabled with a reason while printing.
const TESTZ_STEPS = [1, 0.1, 0.01];

export function LevelingPanel({ btn, printing, status, capabilities, connected }) {
  const levelAction = useStore((s) => s.levelAction);
  const motorsOff = useStore((s) => s.motorsOff);
  const actions = levelingActions(capabilities);
  const reason = reasonDisabled("level", { printing, capabilities, status, connected });
  const dialog = status.manual_probe?.is_active === true;
  return (
    <div className="flex flex-col gap-2">
      {actions.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5">
          {actions.map(({ action, label }) => (
            <button key={action} className={`${btn} text-[10px] px-1`} disabled={!!reason} title={reason || action} onClick={() => levelAction(action)}>{label}</button>
          ))}
        </div>
      )}
      {!actions.length && <div className="text-[10px] opacity-50">No probe, z_tilt, quad_gantry_level, screws_tilt_adjust or bed_screws configured.</div>}
      {dialog && (
        <div className="p-2 rounded border border-amber-500/50 bg-amber-500/10 flex flex-col gap-1.5" role="group" aria-label="Manual probe">
          <div className="text-[10px] font-bold text-amber-500">Manual probe: Z {Number.isFinite(status.manual_probe.z_position) ? status.manual_probe.z_position.toFixed(3) : "?"} mm</div>
          <div className="grid grid-cols-3 gap-1">
            {TESTZ_STEPS.map((s) => <button key={`u${s}`} className={`${btn} text-[10px]`} onClick={() => levelAction("TESTZ", { z: s })}>+{s}</button>)}
            {TESTZ_STEPS.map((s) => <button key={`d${s}`} className={`${btn} text-[10px]`} onClick={() => levelAction("TESTZ", { z: -s })}>−{s}</button>)}
          </div>
          <div className="grid grid-cols-3 gap-1">
            <button className={`${btn} text-[10px] bg-emerald-700 text-white`} onClick={() => levelAction("ACCEPT")}>Accept</button>
            {capabilities.bed_screws ? <button className={`${btn} text-[10px]`} onClick={() => levelAction("ADJUSTED")}>Adjusted</button> : <span />}
            <button className={`${btn} text-[10px] bg-red-700 text-white`} onClick={() => levelAction("ABORT")}>Abort</button>
          </div>
        </div>
      )}
      {reason && <div className="text-[9px] opacity-60">{reason}</div>}
      <button className={`${btn} text-[10px]`} disabled={!!reasonDisabled("motors_off", { printing, connected })}
        title={reasonDisabled("motors_off", { printing, connected }) || "M84"} onClick={() => motorsOff()}>Motors off</button>
    </div>
  );
}
