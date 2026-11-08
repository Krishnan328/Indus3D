// Pure helpers for the file manager and print queue: path handling, sorting, fuzzy matching, filters,
// totals and a small G-code layer parser. No React, no fetch: everything here is unit-tested (filesLogic.test.js).

// ── Paths (always relative to a root, "/" separated, never starting with "/") ───────────────────────────────
export function joinPath(...parts) {
  const out = [];
  for (const part of parts) {
    for (const seg of String(part ?? "").split("/")) {
      if (seg && seg !== ".") out.push(seg);
    }
  }
  return out.join("/");
}

export const parentPath = (p) => (p && p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");
export const baseName = (p) => (p && p.includes("/") ? p.slice(p.lastIndexOf("/") + 1) : p || "");
export const extOf = (name) => {
  const b = baseName(name);
  return b.includes(".") ? b.slice(b.lastIndexOf(".") + 1).toLowerCase() : "";
};

export function isWithin(path, folder) {
  return folder === "" || path === folder || path.startsWith(`${folder}/`);
}

/** [{label, path}] from the root down to ``path`` (the first crumb is the root itself). */
export function breadcrumbs(root, path) {
  const crumbs = [{ label: root, path: "" }];
  let acc = "";
  for (const seg of (path || "").split("/").filter(Boolean)) {
    acc = acc ? `${acc}/${seg}` : seg;
    crumbs.push({ label: seg, path: acc });
  }
  return crumbs;
}

/** Same rules as the server (api/routes/files.py clean_name); the server stays the authority. */
export function validateName(name) {
  if (typeof name !== "string" || !name.trim()) return "Name can not be empty";
  if (name !== name.trim()) return "No leading or trailing spaces";
  if (name === "." || name === "..") return "Invalid name";
  if (/[/\\]/.test(name)) return "A name can not contain / or \\";
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\x7f]/.test(name)) return "Invalid character in name";
  if (name.length > 255) return "Name too long";
  return null;
}

/** Name for a copy that does not collide with ``taken``: "a.gcode" -> "a (copy).gcode" -> "a (copy 2).gcode". */
export function uniqueName(name, taken) {
  if (!taken.has(name)) return name;
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  for (let i = 1; i < 1000; i += 1) {
    const cand = `${stem} (copy${i > 1 ? ` ${i}` : ""})${ext}`;
    if (!taken.has(cand)) return cand;
  }
  return `${stem} (${Date.now()})${ext}`;
}

// ── Formatting ─────────────────────────────────────────────────────────────────────────────────────────────
export function formatBytes(n) {
  if (n == null || Number.isNaN(n)) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return "";
  const s = Math.round(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

/** Local wall-clock time of a unix timestamp: "14:32" today, "Tue 02:10" within a week, else a short date. */
export function formatClock(ts, now = Date.now()) {
  if (ts == null) return "";
  const d = new Date(ts * 1000);
  const n = new Date(now);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(n.getFullYear(), n.getMonth(), n.getDate())) / 86400000);
  if (days === 0) return hm;
  if (days > 0 && days < 7) return `${d.toLocaleDateString([], { weekday: "short" })} ${hm}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${hm}`;
}

export function formatFilament(mm, g) {
  const parts = [];
  if (typeof mm === "number" && mm > 0) parts.push(mm >= 1000 ? `${(mm / 1000).toFixed(1)} m` : `${Math.round(mm)} mm`);
  if (typeof g === "number" && g > 0) parts.push(`${g >= 100 ? Math.round(g) : g.toFixed(1)} g`);
  return parts.join(" · ");
}

// ── Kinds ──────────────────────────────────────────────────────────────────────────────────────────────────
const IMAGE = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp"]);
const VIDEO = new Set(["mp4", "webm", "mov"]);
const MARKDOWN = new Set(["md", "markdown"]);
const GCODE = new Set(["gcode", "g", "gco", "gc", "nc", "ufp"]);
const TEXT = new Set(["txt", "cfg", "conf", "ini", "json", "log", "csv", "yaml", "yml", "toml", "py", "sh", "service",
  "jinja", "j2", "xml", "html", "htm", "css", "js", "md", "markdown", "gcode", "g", "gco", "gc", "nc", "macro", "env", "list"]);

export function fileKind(name) {
  const e = extOf(name);
  if (GCODE.has(e)) return "gcode";
  if (IMAGE.has(e)) return "image";
  if (VIDEO.has(e)) return "video";
  if (MARKDOWN.has(e)) return "markdown";
  if (["zip", "gz", "tar", "tgz", "7z"].includes(e)) return "archive";
  if (TEXT.has(e) || (!e && /^(README|LICENSE|Makefile)/i.test(baseName(name)))) return "text";
  return "other";
}

export const isEditable = (name) => ["text", "markdown", "gcode"].includes(fileKind(name));
export const canPrint = (name) => fileKind(name) === "gcode" && extOf(name) !== "ufp";

// ── Filters ────────────────────────────────────────────────────────────────────────────────────────────────
const BACKUP_RES = [
  /-\d{8}_\d{6}\.(cfg|conf)$/i,           // Klipper SAVE_CONFIG backup: printer-20240101_120000.cfg
  /\.(cfg|conf)\.\d{8}[\w-]*$/i,
  /\.(bkp|bak|backup|old|orig)$/i,        // Moonraker / Crowsnest / editors
  /~$/,
];
const TEMP_RES = [/\.(part|tmp|temp|upload|crdownload)$/i, /^\.?tmp[_-]/i, /^\.indus3d-zip-/i];
const ROLLED_LOG_RES = [/\.log\.(\d{4}-\d{2}-\d{2}|\d+)(\.gz)?$/i, /\.log\.gz$/i];

export const isHiddenName = (name) => name.startsWith(".");
export const isBackupName = (name) => BACKUP_RES.some((r) => r.test(name));
export const isTempName = (name) => TEMP_RES.some((r) => r.test(name));
export const isRolledLog = (name) => ROLLED_LOG_RES.some((r) => r.test(name));
export const wasPrinted = (entry) => Boolean(entry?.meta?.print_start_time || entry?.meta?.job_id);

export const DEFAULT_FILTERS = { hidden: false, backups: false, temp: false, logs: false, printed: true };

/** ``filters`` are "show" switches. Folders are only affected by the hidden switch. */
export function applyFilters(entries, filters = DEFAULT_FILTERS) {
  return entries.filter((e) => {
    if (!filters.hidden && isHiddenName(e.name)) return false;
    if (e.type === "dir") return true;
    if (!filters.backups && isBackupName(e.name)) return false;
    if (!filters.temp && isTempName(e.name)) return false;
    if (!filters.logs && isRolledLog(e.name)) return false;
    if (!filters.printed && wasPrinted(e)) return false;
    return true;
  });
}

// ── Sorting ────────────────────────────────────────────────────────────────────────────────────────────────
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export const SORT_KEYS = {
  name: (e) => e.name,
  size: (e) => (e.type === "dir" ? null : e.size),
  modified: (e) => e.modified,
  slicer: (e) => e.meta?.slicer?.toString().toLowerCase() || null,
  filament: (e) => (e.meta?.filament_type || e.meta?.filament_name || "").toString().toLowerCase() || null,
  temps: (e) => (e.meta?.first_layer_extr_temp ?? null),
  layer_height: (e) => e.meta?.layer_height ?? null,
  estimated_time: (e) => e.meta?.estimated_time ?? null,
  last_print: (e) => e.meta?.print_start_time ?? null,
};

/** Folders first, then ``key`` in ``dir`` ("asc"|"desc"); entries without a value always sort last; ties by name. */
export function sortEntries(entries, key = "name", dir = "asc") {
  const get = SORT_KEYS[key] || SORT_KEYS.name;
  const sign = dir === "desc" ? -1 : 1;
  return [...entries].sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    if (a.type === "dir" && key !== "name" && key !== "modified") return collator.compare(a.name, b.name);
    const va = get(a);
    const vb = get(b);
    const na = va == null || va === "";
    const nb = vb == null || vb === "";
    if (na !== nb) return na ? 1 : -1;
    if (!na) {
      const c = typeof va === "number" && typeof vb === "number" ? va - vb : collator.compare(String(va), String(vb));
      if (c !== 0) return c * sign;
    }
    return collator.compare(a.name, b.name);
  });
}

// ── Fuzzy matching (go-to-file) ────────────────────────────────────────────────────────────────────────────
/** Subsequence match, -1 if ``query`` is not a subsequence of ``text``. Higher is better: consecutive
 *  characters, word starts and matches in the file name (after the last "/") score more, long paths less. */
export function fuzzyScore(query, text) {
  const q = query.toLowerCase().replace(/\s+/g, "");
  if (!q) return 0;
  const t = text.toLowerCase();
  const nameStart = t.lastIndexOf("/") + 1;
  let score = 0;
  let ti = 0;
  let prev = -2;
  for (let qi = 0; qi < q.length; qi += 1) {
    const idx = t.indexOf(q[qi], ti);
    if (idx === -1) return -1;
    let s = 1;
    if (idx === prev + 1) s += 4;                                           // consecutive
    if (idx === 0 || /[\s/_.\-()]/.test(t[idx - 1])) s += 3;                // start of a word / path segment
    if (idx >= nameStart) s += 2;                                           // inside the file name
    score += s;
    prev = idx;
    ti = idx + 1;
  }
  if (t.includes(q)) score += 6;                                            // contiguous substring
  return score - text.length * 0.02;
}

export function fuzzyFilter(query, items, getText = (x) => x, limit = 50) {
  if (!query.trim()) return items.slice(0, limit);
  const scored = [];
  for (const item of items) {
    const s = fuzzyScore(query, getText(item));
    if (s >= 0) scored.push([s, item]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, limit).map((x) => x[1]);
}

/** Plain live search over names: every whitespace separated term must occur (case-insensitive). */
export function matchesSearch(name, query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const n = name.toLowerCase();
  return terms.every((t) => n.includes(t));
}

// ── Queue totals (mirror of backend summarize, used for what-if numbers in the UI) ─────────────────────────
export function queueTotals(jobs, remainingCurrentS = 0, now = Date.now() / 1000) {
  let timeS = 0;
  let mm = 0;
  let g = 0;
  let missing = 0;
  let cursor = now + Math.max(0, remainingCurrentS || 0);
  for (const j of jobs) {
    const m = j.meta || {};
    if (typeof m.estimated_time === "number" && m.estimated_time > 0) {
      timeS += m.estimated_time;
      if (cursor != null) cursor += m.estimated_time;
    } else {
      missing += 1;
      cursor = null;
    }
    if (typeof m.filament_total === "number") mm += m.filament_total;
    if (typeof m.filament_weight_total === "number") g += m.filament_weight_total;
  }
  return { count: jobs.length, timeS, filamentMm: mm, filamentG: g, missing, finishTs: jobs.length && cursor != null ? cursor : null };
}

/** Move element ``from`` to index ``to`` (as after a drag-and-drop). */
export function moveItem(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  const [it] = next.splice(from, 1);
  next.splice(to, 0, it);
  return next;
}

/** A readable message from a files/queue API error body. */
export function apiErrorMessage(status, body) {
  if (body?.unsupported) return "Not available on this Moonraker";
  if (body?.code === "busy") return body.error || "A print is running";
  if (status === 429) return "Too many requests: slow down a little";
  if (status === 502) return "Moonraker is not reachable";
  return body?.error || `HTTP ${status}`;
}

// ── G-code layer parser (for the toolpath preview) ─────────────────────────────────────────────────────────
/**
 * Extruding moves grouped by layer. Handles G90/G91, M82/M83 and G92 E; arcs are drawn as straight chords.
 * Returns {layers: [{z, segs: number[]}], bounds: {minX,maxX,minY,maxY}, truncated}; ``segs`` is x0,y0,x1,y1,...
 */
export function parseGcodeLayers(text, { maxSegments = 300000 } = {}) {
  const layers = [];
  let cur = null;
  let x = 0; let y = 0; let z = 0; let e = 0;
  let absXYZ = true; let absE = true;
  let total = 0;
  let truncated = false;
  const b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    let line = lines[i];
    const semi = line.indexOf(";");
    if (semi >= 0) line = line.slice(0, semi);
    line = line.trim();
    if (!line) continue;
    const word = line.split(/\s+/, 1)[0].toUpperCase();
    if (word === "G90") { absXYZ = true; continue; }          // Klipper: G90/G91 never change extruder mode
    if (word === "G91") { absXYZ = false; continue; }
    if (word === "M82") { absE = true; continue; }
    if (word === "M83") { absE = false; continue; }
    if (word === "G92") {
      const m = /E(-?[\d.]+)/i.exec(line);
      if (m) e = parseFloat(m[1]);
      continue;
    }
    if (word !== "G0" && word !== "G1" && word !== "G2" && word !== "G3") continue;
    let nx = x; let ny = y; let nz = z; let ne = e;
    let hasE = false;
    for (const tok of line.split(/\s+/).slice(1)) {
      const c = tok[0].toUpperCase();
      const v = parseFloat(tok.slice(1));
      if (Number.isNaN(v)) continue;
      if (c === "X") nx = absXYZ ? v : x + v;
      else if (c === "Y") ny = absXYZ ? v : y + v;
      else if (c === "Z") nz = absXYZ ? v : z + v;
      else if (c === "E") { ne = absE ? v : e + v; hasE = true; }
    }
    const extruding = hasE && ne > e && (nx !== x || ny !== y);
    if (nz !== z) z = nz;
    if (extruding) {
      if (!cur || cur.z !== z) {
        cur = { z, segs: [] };
        layers.push(cur);
      }
      if (total >= maxSegments) { truncated = true; break; }
      cur.segs.push(x, y, nx, ny);
      total += 1;
      b.minX = Math.min(b.minX, x, nx); b.maxX = Math.max(b.maxX, x, nx);
      b.minY = Math.min(b.minY, y, ny); b.maxY = Math.max(b.maxY, y, ny);
    }
    x = nx; y = ny; e = ne;
  }
  return { layers, bounds: layers.length ? b : { minX: 0, maxX: 1, minY: 0, maxY: 1 }, truncated };
}

/** The thumbnail closest to ``target`` px, preferring one at least that large. ``thumbs`` is meta.thumbnails. */
export function pickThumbnail(thumbs, target = 64) {
  if (!Array.isArray(thumbs) || !thumbs.length) return null;
  const size = (t) => Math.max(t.width || 0, t.height || 0);
  const bigger = thumbs.filter((t) => size(t) >= target).sort((a, b) => size(a) - size(b));
  if (bigger.length) return bigger[0];
  return [...thumbs].sort((a, b) => size(b) - size(a))[0];
}
