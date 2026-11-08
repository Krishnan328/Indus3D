import React, { useEffect } from "react";
import { Power, ShieldCheck, ShieldOff, AlertTriangle, Zap, Activity } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

// ── Power devices panel ───────────────────────────────────────────────────────
// Two things live here: manual on/off for any Moonraker [power] device (the
// Mainsail feature Indus3D didn't have), visibility into whether the
// automatic thermal-runaway cutoff (core/alert_actions.py) is actually armed,
// and real-time AC electrical telemetry from the PZEM-004T power monitor.
//
// The one check Mainsail's power widget doesn't do: if the configured cutoff
// device has locked_while_printing=true in moonraker.conf, Moonraker will
// silently refuse the cutoff during a print — exactly when it's needed. We
// can detect that mismatch client-side and surface it instead of letting it
// fail silently the one time it matters.
export function PowerPanel() {
  const devices        = useStore((s) => s.powerDevices);
  const cutoffConfig    = useStore((s) => s.powerCutoffConfig);
  const powerMetrics    = useStore((s) => s.power);
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

  const isPzemLive = powerMetrics.connected || powerMetrics.voltage != null;

  return (
    <div className={`p-4 ${t.panel} flex flex-col gap-4`}>
      {/* ── Live PZEM-004T Electrical Telemetry ── */}
      <div>
        <div className="flex items-center justify-between mb-2 text-amber-400">
          <div className="flex items-center gap-2">
            <Zap size={16} />
            <h3 className={t.heading}>AC Electrical Stats (PZEM-004T)</h3>
          </div>
          <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded border ${
            isPzemLive
              ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
              : "text-neutral-400 bg-neutral-500/10 border-neutral-500/20"
          }`}>
            {isPzemLive ? "ONLINE" : "OFFLINE"}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
          {[
            ["Voltage", powerMetrics.voltage != null ? `${powerMetrics.voltage.toFixed(1)} V` : "—"],
            ["Current", powerMetrics.current != null ? `${powerMetrics.current.toFixed(3)} A` : "—"],
            ["Active Power", (powerMetrics.power != null || powerMetrics.power_w != null) ? `${(powerMetrics.power ?? powerMetrics.power_w).toFixed(1)} W` : "—"],
            ["Total Energy", (powerMetrics.energy != null || powerMetrics.energy_wh != null)
              ? ((powerMetrics.energy ?? powerMetrics.energy_wh) >= 1000
                  ? `${((powerMetrics.energy ?? powerMetrics.energy_wh) / 1000).toFixed(2)} kWh`
                  : `${powerMetrics.energy ?? powerMetrics.energy_wh} Wh`)
              : "—"],
            ["Frequency", powerMetrics.frequency != null ? `${powerMetrics.frequency.toFixed(1)} Hz` : "—"],
            ["Power Factor", powerMetrics.power_factor != null ? `${powerMetrics.power_factor.toFixed(2)}` : "—"],
          ].map(([label, val]) => (
            <div key={label} className={`p-2 ${t.cell} flex flex-col items-center justify-center`}>
              <span className={`${t.label} text-[10px]`}>{label}</span>
              <span className="font-semibold">{val}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Moonraker Relay / Power Devices ── */}
      <div className="border-t border-slate-700/40 pt-3">
        <div className="flex items-center gap-2 mb-2 text-amber-400">
          <Power size={16} />
          <h3 className={t.heading}>Switch Devices</h3>
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
          ? <div className="text-[11px] opacity-40 italic text-center py-1">No [power] switch devices configured in moonraker.conf</div>
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
    </div>
  );
}
