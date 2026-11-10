// Small shared formatter for the "Date Format" / "Time Format" preferences
// in Settings > General (uiPrefs.dateFormat / uiPrefs.timeFormat). Import
// this instead of calling toLocaleDateString/toLocaleTimeString directly
// anywhere the user is likely to actually look at a timestamp.
import { useStore } from "./store";

function pad(n) { return String(n).padStart(2, "0"); }

export function formatDate(date, dateFormat) {
  const d = date instanceof Date ? date : new Date(date);
  if (isNaN(d)) return "";
  switch (dateFormat) {
    case "iso": return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    case "dmy": return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
    case "mdy": return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}/${d.getFullYear()}`;
    case "browser":
    default: return d.toLocaleDateString();
  }
}

export function formatTime(date, timeFormat) {
  const d = date instanceof Date ? date : new Date(date);
  if (isNaN(d)) return "";
  switch (timeFormat) {
    case "24h": return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    case "12h": return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true });
    case "browser":
    default: return d.toLocaleTimeString();
  }
}

// Convenience hook: components call useDateTimeFormat() once and get back
// formatters already bound to the current preference, instead of reading
// uiPrefs and importing formatDate/formatTime separately every time.
export function useDateTimeFormat() {
  const dateFormat = useStore((s) => s.uiPrefs.dateFormat);
  const timeFormat = useStore((s) => s.uiPrefs.timeFormat);
  return {
    formatDate: (date) => formatDate(date, dateFormat),
    formatTime: (date) => formatTime(date, timeFormat),
  };
}
