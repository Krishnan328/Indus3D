import React from "react";
import { AlertTriangle } from "lucide-react";
import { useStore } from "../store";
import { useThemeTokens } from "../theme";
import { Card, Resource, Stat } from "./shared";
import { fmtKb, fmtMhz, fmtNum, fmtRate, fmtUptime, tone } from "./format";

function ThrottleCard({ th }) {
  const t = useThemeTokens();
  if (!th?.supported) {
    return <div className={`p-2 text-xs opacity-60 ${t.cell}`}>Throttle state is only reported by Raspberry Pi hosts.</div>;
  }
  const bad = th.now.length > 0;
  return (
    <div className={`p-2 text-xs flex items-start gap-2 ${t.cell} ${bad ? "ring-1 ring-red-500/60" : ""}`}>
      {bad && <AlertTriangle size={14} className="text-red-500 mt-0.5 shrink-0" />}
      <div>
        <span className={t.label}>Power / throttling</span>
        {bad ? <span className="text-red-500 font-bold">Now: {th.now.join(", ")}</span> : <span className="text-emerald-500">OK right now</span>}
        {th.since_boot.length > 0 && <span className="block opacity-70 mt-0.5">Since boot: {th.since_boot.join(", ")}</span>}
      </div>
    </div>
  );
}

export function HostPanel() {
  const res = useStore((s) => s.systemData.info);
  const t = useThemeTokens();
  return (
    <Resource res={res} what="Host information">
      {(d) => {
        const h = d.host;
        const sec = d.sections || {};
        return (
          <div className="flex flex-col gap-4">
            {d.simulated && <div className={`p-2 text-xs ${t.cell}`}>Simulator: these values are stand-ins, not your printer host.</div>}
            <Card title="Host">
              <div className="grid grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-4 gap-2">
                <Stat label="Hostname" value={h.hostname} />
                <Stat label="OS" value={h.os} sub={h.arch} />
                <Stat label="Model" value={h.model} sub={h.cpu_count ? `${h.cpu_count} cores` : null} />
                <Stat label="Uptime" value={fmtUptime(h.uptime_s)} />
                <Stat label="CPU load" value={fmtNum(h.cpu_usage_pct, 0, " %")} tone={tone(h.cpu_usage_pct, 70, 90)} />
                <Stat label="CPU temp" value={fmtNum(h.cpu_temp_c, 1, " °C")} tone={tone(h.cpu_temp_c, 70, 80)} />
                <Stat label="Memory" value={`${fmtKb(h.memory_used_kb)} / ${fmtKb(h.memory_total_kb)}`}
                  sub={h.memory_used_pct != null ? `${h.memory_used_pct} % used` : null} tone={tone(h.memory_used_pct, 80, 92)} />
                <Stat label="Python" value={h.python} sub={h.virtualization && h.virtualization !== "none" ? h.virtualization : null} />
              </div>
              <div className="mt-3"><ThrottleCard th={h.throttle} /></div>
              {h.sd_card && <div className="mt-2 text-[11px] opacity-60">SD card: {h.sd_card.product} {h.sd_card.capacity}</div>}
            </Card>

            <Card title="Klipper and Moonraker">
              <div className="grid grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-4 gap-2">
                <Stat label="Klipper" value={h.klipper?.state ?? "—"} sub={h.klipper?.version}
                  tone={h.klipper && h.klipper.state !== "ready" ? "text-amber-500" : ""} />
                <Stat label="Moonraker" value={h.moonraker?.version} sub={h.moonraker?.api_version ? `API ${h.moonraker.api_version}` : null} />
                <Stat label="WebSocket clients" value={h.websocket_connections ?? "—"} />
                <Stat label="Failed components" value={h.moonraker?.failed_components?.length ? h.moonraker.failed_components.join(", ") : "none"}
                  tone={h.moonraker?.failed_components?.length ? "text-red-500" : ""} />
              </div>
              {h.klipper?.message && h.klipper.state !== "ready" && <p className="mt-2 text-xs text-amber-500 whitespace-pre-wrap">{h.klipper.message}</p>}
              {Object.entries(sec).filter(([, s]) => !s.ok && !s.unsupported).map(([name, s]) => (
                <p key={name} className="mt-2 text-[11px] text-amber-500">{name}: {s.error}</p>
              ))}
              {Object.entries(sec).filter(([, s]) => s.unsupported).map(([name]) => (
                <p key={name} className="mt-2 text-[11px] opacity-60">{name}: not available on this Moonraker</p>
              ))}
            </Card>

            {h.network?.length > 0 && (
              <Card title="Network">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {h.network.map((n) => <Stat key={n.name} label={n.name} value={n.ip || "no address"} sub={fmtRate(n.bandwidth_bps)} />)}
                </div>
              </Card>
            )}
          </div>
        );
      }}
    </Resource>
  );
}

export function McuPanel() {
  const res = useStore((s) => s.systemData.info);
  const t = useThemeTokens();
  return (
    <Resource res={res} what="MCU information">
      {(d) => {
        const sec = d.sections?.mcus;
        if (sec && sec.unsupported) return <div className={`p-3 text-xs ${t.cell}`}>MCU objects are not available on this Moonraker.</div>;
        if (sec && !sec.ok) return <div className={`p-3 text-xs ${t.cell}`}>Klipper has not reported its MCUs ({sec.error}). This is normal while the printer is off or restarting.</div>;
        if (!d.mcus?.length) return <div className={`p-3 text-xs ${t.cell}`}>Klipper reports no MCUs.</div>;
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {d.mcus.map((m) => (
              <Card key={m.object} title={`MCU: ${m.name}`} right={<span className="text-[10px] opacity-60 font-mono">{m.chip || "unknown chip"}</span>}>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <Stat label="Clock" value={fmtMhz(m.clock_freq)} sub={m.freq ? `measured ${fmtMhz(m.freq)}` : null} />
                  <Stat label="Awake" value={fmtNum(m.awake_pct, 1, " %")} tone={m.awake_pct >= 60 ? "text-amber-500" : ""} />
                  <Stat label="Task avg" value={fmtNum(m.task_avg_us, 1, " µs")} />
                  <Stat label="Retransmits" value={m.bytes_retransmit ?? "—"} tone={m.bytes_retransmit > 0 ? "text-amber-500" : ""} />
                  <Stat label="Invalid bytes" value={m.bytes_invalid ?? "—"} tone={m.bytes_invalid > 0 ? "text-amber-500" : ""} />
                  <Stat label="Round trip" value={fmtNum(m.srtt != null ? m.srtt * 1000 : null, 1, " ms")} />
                </div>
                <p className="mt-2 text-[11px] font-mono opacity-70 break-all">Firmware {m.version || "unknown"}</p>
                {m.build_versions && <p className="text-[10px] font-mono opacity-50 break-all">{m.build_versions}</p>}
              </Card>
            ))}
          </div>
        );
      }}
    </Resource>
  );
}
