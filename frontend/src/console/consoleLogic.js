/**
 * consoleLogic.js — pure (no React) helper functions for the Terminal console.
 *
 * All functions here are side-effect-free and independently unit-testable.
 */

// ── Filter engine ─────────────────────────────────────────────────────────────

/**
 * Filter mode identifiers.
 * @typedef {"contains"|"starts-with"|"regex"} FilterMode
 */

/**
 * Validate a regex pattern string.
 * @param {string} pattern
 * @returns {boolean} true if pattern compiles without error
 */
export function isValidRegex(pattern) {
  if (!pattern) return true;
  try {
    // eslint-disable-next-line no-new
    new RegExp(pattern);
    return true;
  } catch {
    return false;
  }
}

/**
 * Build a predicate that tests a single line string against the filter params.
 *
 * Returns null when the filter is inactive (empty pattern or invalid regex).
 *
 * @param {string}     pattern
 * @param {FilterMode} mode
 * @param {boolean}    caseSensitive
 * @returns {((text: string) => boolean)|null}
 */
export function buildFilterPredicate(pattern, mode, caseSensitive) {
  if (!pattern) return null;

  const flags = caseSensitive ? "" : "i";

  if (mode === "regex") {
    if (!isValidRegex(pattern)) return null;
    const re = new RegExp(pattern, flags);
    return (text) => re.test(text);
  }

  if (mode === "starts-with") {
    return caseSensitive
      ? (text) => text.startsWith(pattern)
      : (text) => text.toLowerCase().startsWith(pattern.toLowerCase());
  }

  // "contains" (default)
  return caseSensitive
    ? (text) => text.includes(pattern)
    : (text) => text.toLowerCase().includes(pattern.toLowerCase());
}

/**
 * Apply the filter predicate to an array of parsed line objects.
 * Lines are objects with at least a `text` string property.
 *
 * Returns the same array reference if predicate is null (no filtering).
 *
 * @param {Array<{text: string}>} lines
 * @param {((text: string) => boolean)|null} predicate
 * @returns {Array<{text: string}>}
 */
export function applyFilter(lines, predicate) {
  if (!predicate) return lines;
  return lines.filter((l) => predicate(l.text ?? ""));
}

// ── Autocomplete engine ───────────────────────────────────────────────────────

/** Static list of common G/M codes per the spec. */
export const STATIC_GCODES = [
  "G0", "G1", "G28", "G29", "G34", "G80", "G92",
  "M84", "M104", "M109", "M140", "M190",
  "M220", "M221", "M400", "M600", "M603", "M701", "M702",
];

/**
 * Build a deduplicated, sorted completion candidate list.
 *
 * @param {string[]} quickCommands  — QUICK_COMMANDS from the component
 * @param {string[]} macros         — macros from the Zustand store
 * @returns {string[]}
 */
export function buildCompletionList(quickCommands, macros) {
  return Array.from(
    new Set([
      ...STATIC_GCODES,
      ...(quickCommands || []),
      ...(macros || []).filter((m) => typeof m === "string" && !m.startsWith("_")),
    ])
  ).sort();
}

/**
 * Find completions for the current input prefix.
 *
 * @param {string}   input       — current text in the console input field
 * @param {string[]} candidates  — full list from buildCompletionList()
 * @returns {string[]}           — matching entries (up to 10, case-insensitive prefix match)
 */
export function getCompletions(input, candidates) {
  if (!input) return [];
  const lower = input.toLowerCase();
  return candidates
    .filter((c) => c.toLowerCase().startsWith(lower))
    .slice(0, 10);
}

// ── Built-in filter presets ───────────────────────────────────────────────────

/**
 * @typedef {{name: string, pattern: string, mode: FilterMode, caseSensitive: boolean, builtin?: boolean}} FilterPreset
 */

/** @type {FilterPreset[]} */
export const BUILTIN_PRESETS = [
  { name: "Errors only",       pattern: "!!",                    mode: "starts-with", caseSensitive: true,  builtin: true },
  { name: "Indus3D messages",  pattern: "[INDUS]",               mode: "starts-with", caseSensitive: true,  builtin: true },
  { name: "User commands",     pattern: ">>> ",                  mode: "starts-with", caseSensitive: true,  builtin: true },
  { name: "M105 temps",        pattern: "^ok (T|B)\\d*:-?\\d",  mode: "regex",       caseSensitive: false, builtin: true },
  { name: "No SD status",      pattern: "echo:SD printing byte", mode: "starts-with", caseSensitive: false, builtin: true },
];

// ── localStorage helpers ──────────────────────────────────────────────────────

const FILTER_MODE_KEY   = "indus3d_console_filter_mode";
const USER_PRESETS_KEY  = "indus3d_console_presets";

/** @returns {FilterMode} */
export function loadFilterMode() {
  try {
    const v = localStorage.getItem(FILTER_MODE_KEY);
    if (v === "contains" || v === "starts-with" || v === "regex") return v;
  } catch { /* private / no-storage mode */ }
  return "contains";
}

/** @param {FilterMode} mode */
export function saveFilterMode(mode) {
  try { localStorage.setItem(FILTER_MODE_KEY, mode); } catch { /* ignore */ }
}

/** @returns {FilterPreset[]} */
export function loadUserPresets() {
  try {
    const raw = localStorage.getItem(USER_PRESETS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, 5);            // cap at 5
  } catch {
    return [];
  }
}

/** @param {FilterPreset[]} presets */
export function saveUserPresets(presets) {
  try {
    localStorage.setItem(USER_PRESETS_KEY, JSON.stringify(presets.slice(0, 5)));
  } catch { /* ignore */ }
}
