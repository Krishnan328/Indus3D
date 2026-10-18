import React, { useEffect } from "react";
import { Power, ShieldCheck, ShieldOff, AlertTriangle } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

// ── Power devices panel ───────────────────────────────────────────────────────
// Two things live here: manual on/off for any Moonraker [power] device (the
// Mainsail feature Indus3D didn't have), and visibility into whether the
// automatic thermal-runaway cutoff (core/alert_actions.py) is actually armed.
//
// The one check Mainsail's power widget doesn't do: if the configured cutoff
// device has locked_while_printing=true in moonraker.conf, Moonraker will
// silently refuse the cutoff during a print — exactly when it's needed. We
// can detect that mismatch client-side and surface it instead of letting it
// fail silently the one time it matters.
export function PowerPanel() {
  const devices        = useStore((s) => s.powerDevices);
  const cutoffConfig    = useStore((s) => s.powerCutoffConfig);
  const fetchDevices    = useStore((s) => s.fetchPowerDevices);
  const fetchCutoffCfg  = useStore((s) => s.fetchPowerCutoffConfig);
  const setPowerDevice  = useStore((s) => s.setPowerDevice);
  const confirmPowerToggle = useStore((s) => s.uiPrefs.confirmPowerToggle);
  const t = useThemeTokens();

  useEffect(() => {
    fetchDevices();
    fetchCutoffCfg();
  }, [fetchCutoffCfg, fetchDevices]);

  const handleToggle = (device, nextStatus) => {
    if (confirmPowerToggle && !window.confirm(`Turn ${nextStatus === "on" ? "on" : "off"} '${device}'?`)) return;
    setPowerDevice(device, nextStatus);
  };

  const cutoffDevice = cutoffConfig.enabled
    ? devices.find((d) => d.device === cutoffConfig.device)
    : null;
  const misconfigured = cutoffConfig.enabled && cutoffDevice?.locked_while_printing;
  const deviceMissing  = cutoffConfig.enabled && cutoffConfig.device && !cutoffDevice && devices.length > 0;

  return (
    <div className={`p-4 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-amber-400">
        <Power size={16} />
        <h3 className={t.heading}>Power Devices</h3>
      </div>

      <div className={`flex items-start gap-2 px-3 py-2 mb-3 text-xs ${t.cell} ${
        misconfigured || deviceMissing ? "border-red-500 text-red-400" : cutoffConfig.enabled ? "border-green-600" : "opacity-60"
      }`}>
        {cutoffConfig.enabled
          ? (misconfigured
              ? <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              : <ShieldCheck size={14} className="mt-0.5 shrink-0 text-green-500" />)
          : <ShieldOff size={14} className="mt-0.5 shrink-0" />}
        <div>
          {!cutoffConfig.enabled && "Automatic runaway power cutoff is disabled (indus_overrides.cfg)."}
          {cutoffConfig.enabled && !cutoffConfig.device && "Cutoff enabled but no device configured — set power_cutoff_device."}
          {cutoffConfig.enabled && deviceMissing && `Configured device '${cutoffConfig.device}' not found in Moonraker's power devices.`}
          {cutoffConfig.enabled && misconfigured && `'${cutoffConfig.device}' has locked_while_printing=true — the cutoff will be REFUSED during a print. Remove that flag in moonraker.conf.`}
          {cutoffConfig.enabled && cutoffDevice && !misconfigured && `Armed — a thermal runaway will cut power to '${cutoffConfig.device}'.`}
        </div>
      </div>

      {!devices.length
        ? <div className="text-[11px] opacity-40 italic text-center py-2">No [power] devices configured in moonraker.conf</div>
        : <div className="flex flex-col gap-1.5">
            {devices.map((d) => (
              <div key={d.device} className={`flex items-center justify-between px-3 py-1.5 text-xs ${t.cell}`}>
                <span className="font-mono">
                  {d.device}
                  {d.locked_while_printing && <span className="ml-1.5 opacity-50">(locked while printing)</span>}
                </span>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold uppercase ${d.status === "on" ? "text-green-500" : "opacity-50"}`}>{d.status}</span>
                  <button
                    onClick={() => handleToggle(d.device, d.status === "on" ? "off" : "on")}
                    className={`px-2.5 py-1 text-[10px] font-bold uppercase ${t.chip} ${d.status === "on" ? "bg-red-700 text-white" : "bg-green-700 text-white"}`}
                  >
                    {d.status === "on" ? "Turn off" : "Turn on"}
                  </button>
                </div>
              </div>
            ))}
          </div>
      }
    </div>
  );
}
