import React, { useEffect } from "react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";
import { AlertBanners } from "./system/AlertBanners";
import { HostPanel, McuPanel } from "./system/HostPanel";
import { ServicesPanel } from "./system/ServicesPanel";
import { UpdatesPanel } from "./system/UpdatesPanel";
import { BackupsPanel } from "./system/BackupsPanel";
import { DevicesPanel } from "./system/DevicesPanel";

// System page: host, MCUs, services, updates, backups and devices, from the backend's /api/v1/system/*
// proxies to Moonraker. Data is polled only while this page is mounted and the browser tab is visible
// (see slices/systemSlice.js). Anything this Moonraker cannot do says so instead of failing.
const TABS = [
  ["host", "Host"], ["mcus", "MCUs"], ["services", "Services"], ["updates", "Updates"], ["backups", "Backups"], ["devices", "Devices"],
];
const PANELS = { host: HostPanel, mcus: McuPanel, services: ServicesPanel, updates: UpdatesPanel, backups: BackupsPanel, devices: DevicesPanel };

export function SystemPage() {
  const t = useThemeTokens();
  const tab = useStore((s) => s.systemTab);
  const setTab = useStore((s) => s.setSystemTab);
  const subscribe = useStore((s) => s.subscribeSystem);
  const refresh = useStore((s) => s.refreshSystem);
  const notice = useStore((s) => s.systemNotice);
  const info = useStore((s) => s.systemData.info);
  const Panel = PANELS[tab] || HostPanel;

  useEffect(() => subscribe(), [subscribe]);          // polls only while this page is open

  const down = info.loaded && !info.ok && !info.data && !info.unsupported;
  return (
    <div className="flex-1 min-w-0 overflow-auto p-4" data-testid="system-page">
      <div className="max-w-5xl mx-auto flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className={t.heading}>System</h2>
          {info.data?.simulated && <span className={`text-[10px] px-2 py-0.5 ${t.chip} bg-gray-500/20`}>simulator</span>}
          <button type="button" onClick={() => refresh()} className={`ml-auto px-2 py-1 text-xs border rounded ${t.border} hover:bg-gray-500/10`}>Refresh</button>
        </div>

        {down && (
          <div className="p-3 text-xs rounded border border-red-500/50 bg-red-500/10 text-red-400" role="alert">
            Moonraker is not answering: {info.error}. The printer host may be off or restarting.
          </div>
        )}
        {notice && (
          <div role="status" className={`px-3 py-2 text-xs rounded border ${notice.tone === "ok" ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-500" : "border-red-500/50 bg-red-500/10 text-red-400"}`}>{notice.text}</div>
        )}

        <AlertBanners onOpenTab={setTab} />

        <div role="tablist" className={`flex flex-wrap gap-1 border-b ${t.border}`}>
          {TABS.map(([id, label]) => (
            <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)}
              className={`px-3 py-2 text-xs uppercase tracking-wider border-b-2 -mb-px transition-colors ${tab === id ? "border-blue-500 font-bold" : "border-transparent opacity-60 hover:opacity-100"}`}>
              {label}
            </button>
          ))}
        </div>

        <div role="tabpanel"><Panel /></div>
      </div>
    </div>
  );
}
