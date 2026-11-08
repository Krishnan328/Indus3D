// Small display helpers for the System page (kept free of React so they can be unit-tested with node --test).

export function fmtKb(kb) {
  if (typeof kb !== "number" || !Number.isFinite(kb)) return "—";
  if (kb >= 1048576) return `${(kb / 1048576).toFixed(1)} GB`;
  if (kb >= 1024) return `${(kb / 1024).toFixed(0)} MB`;
  return `${kb} kB`;
}

export function fmtUptime(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

export function fmtNum(v, digits = 1, unit = "") {
  return typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(digits)}${unit}` : "—";
}

export function fmtRate(bps) {
  if (typeof bps !== "number" || !Number.isFinite(bps)) return "—";
  if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(1)} kB/s`;
  return `${bps.toFixed(0)} B/s`;
}

export function fmtMhz(hz) {
  return typeof hz === "number" && Number.isFinite(hz) ? `${(hz / 1e6).toFixed(hz >= 1e8 ? 0 : 1)} MHz` : "—";
}

/** Tailwind text colour for a load / temperature figure: [warn, bad] thresholds. */
export function tone(value, warn, bad) {
  if (typeof value !== "number") return "";
  if (value >= bad) return "text-red-500";
  if (value >= warn) return "text-amber-500";
  return "";
}

export const STATE_TONE = {
  active: "bg-emerald-500", running: "bg-emerald-500", activating: "bg-amber-500", reloading: "bg-amber-500",
  failed: "bg-red-500", inactive: "bg-gray-400", dead: "bg-gray-400",
};

export const SEVERITY_ORDER = { critical: 0, warning: 1, info: 2 };

/** Alerts sorted most severe first, minus the ones the user dismissed (critical alerts cannot be dismissed). */
export function visibleAlerts(alerts, dismissed) {
  return [...(alerts || [])]
    .filter((a) => a.severity === "critical" || !dismissed?.[a.id])
    .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3));
}

/** True when this component's action must not be offered during a print. */
export function printBusyState(state) {
  return state === "printing" || state === "paused";
}
