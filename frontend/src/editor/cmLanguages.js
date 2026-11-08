// CodeMirror 6 adapters for syntax.js: stream languages for Klipper / Moonraker / G-code, a fold service,
// and a theme + highlight style that follow the app's light/dark mode and theme. Loaded lazily (editor chunk).

import { StreamLanguage, HighlightStyle, syntaxHighlighting, foldService } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { Tag, tags as t } from "@lezer/highlight";
import { startState, tokenizeLine, foldRange } from "./syntax.js";

// Our own tags, each inheriting a standard (unmodified) tag so any generic theme still colors them sensibly.
const T = {
  comment: t.comment,
  section: Tag.define(t.heading),
  sectionId: Tag.define(t.className),
  macroName: Tag.define(t.variableName),
  bracket: t.squareBracket,
  key: t.propertyName,
  variableKey: Tag.define(t.variableName),
  operator: t.operator,
  number: t.number,
  string: t.string,
  bool: t.bool,
  url: t.url,
  pin: Tag.define(t.atom),
  gcodeCmd: Tag.define(t.keyword),
  gcodeParam: Tag.define(t.attributeName),
  gcodeAxis: Tag.define(t.attributeName),
  meta: t.meta,
  autosave: Tag.define(t.docComment),
  jinjaDelim: Tag.define(t.processingInstruction),
  jinjaKeyword: Tag.define(t.controlKeyword),
  jinjaVar: Tag.define(t.variableName),
  jinjaFunc: Tag.define(t.variableName),
  jinjaComment: Tag.define(t.blockComment),
  invalid: t.invalid,
};

const commentTokens = { klipper: { line: "#" }, moonraker: { line: "#" }, gcode: { line: ";" } };

function streamLanguage(mode) {
  return StreamLanguage.define({
    name: mode,
    startState: () => startState(mode),
    copyState: (s) => ({ ...s, spans: s.spans ? s.spans.slice() : [] }),
    token(stream, state) {
      if (stream.sol()) {
        const r = tokenizeLine(stream.string, state.core || startState(mode));
        state.core = r.state;
        state.spans = r.spans;
      }
      const col = stream.pos;
      const spans = state.spans || [];
      const hit = spans.find((s) => s.from <= col && col < s.to);
      if (hit) { stream.pos = Math.min(hit.to, stream.string.length); return hit.type; }
      const next = spans.find((s) => s.from > col);          // plain text up to the next typed span
      stream.pos = next ? next.from : stream.string.length;
      return null;
    },
    blankLine(state) {
      const r = tokenizeLine("", state.core || startState(mode));
      state.core = r.state;
      state.spans = [];
    },
    languageData: { commentTokens: commentTokens[mode] },
    tokenTable: T,
  });
}

function foldFor(mode) {
  return foldService.of((state, lineStart) => {
    const doc = state.doc;
    const line = doc.lineAt(lineStart);
    const lines = [];
    // only the lines that can matter for this block (header .. next header) are needed, but a section can
    // be long: collect lazily up to the end of the document, capped for very large files
    const cap = Math.min(doc.lines, line.number + 4000);
    for (let n = 1; n <= cap; n += 1) lines.push(doc.line(n).text);
    const r = foldRange(lines, line.number - 1, mode);
    if (!r) return null;
    return { from: line.to, to: doc.line(r.to + 1).to };
  });
}

/** CodeMirror language extension(s) for one of syntax.js's modes. */
export function languageFor(mode) {
  if (mode === "klipper" || mode === "moonraker" || mode === "gcode") {
    return mode === "gcode" ? [streamLanguage(mode)] : [streamLanguage(mode), foldFor(mode)];
  }
  if (mode === "json") return [json()];
  if (mode === "markdown") return [markdown(), foldFor("markdown")];
  return [];
}

const PALETTES = {
  dark: {
    comment: "#7f8ea3", section: "#7dd3fc", sectionId: "#fbbf24", macroName: "#fbbf24", bracket: "#94a3b8", key: "#93c5fd", variableKey: "#c4b5fd",
    operator: "#94a3b8", number: "#fda4af", string: "#86efac", bool: "#fdba74", url: "#67e8f9", pin: "#f9a8d4", gcodeCmd: "#c084fc",
    gcodeParam: "#7dd3fc", gcodeAxis: "#93c5fd", meta: "#a3e635", autosave: "#64748b", jinjaDelim: "#f472b6", jinjaKeyword: "#fb7185",
    jinjaVar: "#5eead4", jinjaFunc: "#fcd34d", jinjaComment: "#94a3b8", invalid: "#f87171",
  },
  light: {
    comment: "#6b7280", section: "#0369a1", sectionId: "#b45309", macroName: "#b45309", bracket: "#64748b", key: "#1d4ed8", variableKey: "#6d28d9",
    operator: "#64748b", number: "#be123c", string: "#15803d", bool: "#c2410c", url: "#0e7490", pin: "#be185d", gcodeCmd: "#7e22ce",
    gcodeParam: "#0369a1", gcodeAxis: "#1d4ed8", meta: "#4d7c0f", autosave: "#94a3b8", jinjaDelim: "#be185d", jinjaKeyword: "#be123c",
    jinjaVar: "#0f766e", jinjaFunc: "#a16207", jinjaComment: "#6b7280", invalid: "#dc2626",
  },
};

const SURFACES = {
  classic: { dark: { bg: "#0b0f19", fg: "#e5e7eb", gutter: "#0f1524", line: "#ffffff0d", sel: "#2563eb55" }, light: { bg: "#ffffff", fg: "#111827", gutter: "#f3f4f6", line: "#00000008", sel: "#3b82f633" } },
  brutal: { bg: "#fffdf7", fg: "#111111", gutter: "#f4f1e8", line: "#00000010", sel: "#ffe9a8" },
  creme: { bg: "#fbf6ec", fg: "#3a332a", gutter: "#f1e7d6", line: "#00000008", sel: "#aec6a366" },
};

export function surfaceFor(themeName, dark) {
  if (themeName === "workshop" || themeName === "blueprint") return { ...SURFACES.brutal, dark: false };
  if (themeName === "creme") return { ...SURFACES.creme, dark: false };
  return { ...SURFACES.classic[dark ? "dark" : "light"], dark: !!dark };
}

/** Editor theme + highlight style matching the app (classic dark/light, workshop, blueprint, creme). */
export function themeExtensions(themeName, isDark) {
  const s = surfaceFor(themeName, isDark);
  const pal = PALETTES[s.dark ? "dark" : "light"];
  const view = EditorView.theme({
    "&": { height: "100%", backgroundColor: s.bg, color: s.fg, fontSize: "13px" },
    ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", lineHeight: "1.5" },
    ".cm-content": { caretColor: s.fg, padding: "8px 0" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: s.fg },
    ".cm-gutters": { backgroundColor: s.gutter, color: s.dark ? "#64748b" : "#9ca3af", border: "none" },
    ".cm-activeLine": { backgroundColor: s.line },
    ".cm-activeLineGutter": { backgroundColor: s.line },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": { backgroundColor: s.sel },
    ".cm-foldPlaceholder": { backgroundColor: "transparent", border: "1px solid currentColor", color: s.dark ? "#94a3b8" : "#6b7280", padding: "0 6px" },
    ".cm-searchMatch": { backgroundColor: s.dark ? "#fbbf2455" : "#fde68a" },
    ".cm-searchMatch-selected": { backgroundColor: s.dark ? "#f59e0b88" : "#fbbf24" },
    ".cm-panels": { backgroundColor: s.gutter, color: s.fg },
    ".cm-panels input, .cm-panels button": { color: s.fg },
    ".cm-tooltip": { backgroundColor: s.gutter, color: s.fg, border: "1px solid #64748b55" },
  }, { dark: s.dark });
  const style = HighlightStyle.define(Object.keys(T).map((k) => ({ tag: T[k], color: pal[k], ...(k === "section" ? { fontWeight: "bold" } : {}),
    ...(k === "comment" || k === "autosave" || k === "jinjaComment" ? { fontStyle: "italic" } : {}),
    ...(k === "invalid" ? { textDecoration: "underline wavy" } : {}) })));
  return [view, syntaxHighlighting(style)];
}
