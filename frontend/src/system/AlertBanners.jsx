import React from "react";
import { AlertOctagon, AlertTriangle, Info, X } from "lucide-react";
import { useStore } from "../store";
import { visibleAlerts } from "./format";

const STYLE = {
  critical: ["border-red-500/60 bg-red-500/10 text-red-400", AlertOctagon],
  warning: ["border-amber-500/60 bg-amber-500/10 text-amber-500", AlertTriangle],
  info: ["border-blue-500/40 bg-blue-500/10 text-blue-400", Info],
};

// Active host / Moonraker alerts (throttling, pending updates, outdated Moonraker, announcements, failed
// components). Info and warning banners can be closed for this page load; critical ones stay.
export function AlertBanners({ onOpenTab }) {
  const res = useStore((s) => s.systemData.alerts);
  const dismissed = useStore((s) => s.systemDismissed);
  const dismiss = useStore((s) => s.dismissSystemAlert);
  const alerts = visibleAlerts(res?.data?.alerts, dismissed);
  if (!alerts.length) return null;
  const tabFor = (a) => (a.source === "updates" ? "updates" : a.source === "host" ? "host" : null);
  return (
    <div className="flex flex-col gap-2" aria-label="Active alerts">
      {alerts.map((a) => {
        const [cls, Icon] = STYLE[a.severity] || STYLE.info;
        const tab = tabFor(a);
        return (
          <div key={a.id} role={a.severity === "critical" ? "alert" : "status"} className={`px-3 py-2 text-xs rounded border flex items-start gap-2 ${cls}`}>
            <Icon size={14} className="mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="font-bold">{a.title}</div>
              {a.detail && <div className="opacity-80 break-words">{a.detail}</div>}
            </div>
            {tab && <button type="button" className="ml-auto underline shrink-0" onClick={() => onOpenTab(tab)}>Open</button>}
            {a.severity !== "critical" && (
              <button type="button" aria-label={`Dismiss ${a.title}`} className={`${tab ? "" : "ml-auto"} opacity-60 hover:opacity-100 shrink-0`} onClick={() => dismiss(a.id)}><X size={13} /></button>
            )}
          </div>
        );
      })}
    </div>
  );
}
