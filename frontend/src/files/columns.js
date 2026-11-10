import { formatBytes, formatDuration, formatFilament } from "./filesLogic.js";
import { formatDate } from "../dateFormat.js";

// Column set of the list view. ``min`` is the container width from which a column is shown.
export const GCODE_COLUMNS = [
  { key: "name", label: "Name", width: "minmax(0,1fr)", min: 0 },
  { key: "size", label: "Size", width: "72px", min: 0, align: "right" },
  { key: "modified", label: "Modified", width: "104px", min: 520 },
  { key: "estimated_time", label: "Time", width: "68px", min: 640, align: "right" },
  { key: "filament", label: "Filament", width: "120px", min: 820 },
  { key: "temps", label: "Nozzle/Bed", width: "84px", min: 900 },
  { key: "layer_height", label: "Layer", width: "56px", min: 980, align: "right" },
  { key: "slicer", label: "Slicer", width: "104px", min: 1080 },
  { key: "last_print", label: "Last print", width: "104px", min: 1180 },
];
export const PLAIN_COLUMNS = GCODE_COLUMNS.filter((c) => ["name", "size", "modified"].includes(c.key));

export function visibleColumns(columns, width) {
  return columns.filter((c) => width >= c.min);
}

export function gridTemplate(cols) {
  return `28px ${cols.map((c) => c.width).join(" ")}`;
}

function when(unix, fmt) {
  if (!unix) return "";
  const d = new Date(unix * 1000);
  if (!fmt || fmt === "browser") return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  return formatDate(d, fmt);
}

export function cellText(e, key, dateFormat) {
  const m = e.meta || {};
  switch (key) {
    case "size": return e.type === "dir" ? "" : formatBytes(e.size);
    case "modified": return when(e.modified, dateFormat);
    case "estimated_time": return formatDuration(m.estimated_time);
    case "filament": return [m.filament_type, formatFilament(m.filament_total, m.filament_weight_total)].filter(Boolean).join(" · ");
    case "temps": return m.first_layer_extr_temp != null || m.first_layer_bed_temp != null ? `${m.first_layer_extr_temp ?? "–"}/${m.first_layer_bed_temp ?? "–"}°` : "";
    case "layer_height": return m.layer_height != null ? `${m.layer_height}` : "";
    case "slicer": return m.slicer || "";
    case "last_print": return m.print_start_time ? when(m.print_start_time, dateFormat) : "";
    default: return "";
  }
}

