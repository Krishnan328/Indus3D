// Syntax rules for the editor, written from Klipper's and Moonraker's documented configuration format and
// G-code conventions (no third-party grammar is used). Everything here is pure: a line tokenizer with a small
// immutable state, an outline, and fold ranges, so it is unit-tested in node. cmLanguages.js adapts it to
// CodeMirror.
//
// Token types (the CodeMirror adapter maps each to a highlight tag):
//   comment  section  sectionId  macroName  bracket  key  variableKey  operator  value-ish: number string bool url pin
//   gcodeCmd  gcodeParam  gcodeAxis  meta  autosave  jinjaDelim  jinjaKeyword  jinjaVar  jinjaFunc  jinjaComment  invalid

export const MODES = ["klipper", "moonraker", "gcode", "json", "markdown", "text"];

export function modeForFile(name = "") {
  const base = name.split("/").pop().toLowerCase();
  const ext = base.includes(".") ? base.split(".").pop() : "";
  if (["gcode", "g", "gco", "gc", "nc"].includes(ext)) return "gcode";
  if (ext === "cfg") return "klipper";
  if (ext === "conf" || base.endsWith(".conf.bkp")) return "moonraker";
  if (ext === "json") return "json";
  if (ext === "md" || ext === "markdown") return "markdown";
  return "text";
}

export const startState = (mode = "klipper") => ({ mode, saveConfig: false, gcodeBlock: false, jinja: null, gcodeLine: false });

const SAVE_MARKER = /^#\*#\s*<-+\s*SAVE_CONFIG\s*-+>\s*$/;
const SECTION = /^(\s*)\[([^\]]*)\]/;
const KEY = /^([A-Za-z_][\w.-]*)(\s*)([:=])/;
const GCODE_KEYS = /^(gcode|[a-z0-9_]+_gcode)$/i;
const JINJA_KEYWORDS = new Set(["if", "elif", "else", "endif", "for", "endfor", "in", "set", "and", "or", "not", "is", "macro",
  "endmacro", "include", "import", "filter", "endfilter", "do", "raw", "endraw", "call", "endcall", "with", "endwith",
  "true", "false", "none", "True", "False", "None", "namespace", "loop", "from", "as", "recursive"]);
const JINJA_VARS = new Set(["printer", "params", "rawparams", "gcode_macro", "action_emergency_stop", "action_respond_info",
  "action_raise_error", "action_call_remote_method", "gcode", "kwargs"]);

const PIN = /^[!^~]*(?:[A-Za-z_][\w-]*:)?(?:P[A-Z]\d+(?:\.\d+)?|gpio\d+|gpiochip\d+\/gpio\d+)(?![\w.])/;
const NUMBER = /^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?(?![\w.])/i;
const URL_RE = /^https?:\/\/[^\s,]+/i;
const BOOL = /^(?:true|false|none)(?![\w.])/i;
const STRING = /^"(?:[^"\\]|\\.)*"?|^'(?:[^'\\]|\\.)*'?/;

function push(spans, from, to, type) {
  if (to > from && type) spans.push({ from, to, type });
}

/** Typed spans for a config value (right of ``:`` / ``=``). ``base`` is the offset of ``text`` within the line. */
function tokenizeValue(text, base, mode) {
  const spans = [];
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    const prev = i === 0 ? " " : text[i - 1];
    // a trailing comment needs whitespace (or the start) before it
    if ((ch === "#" || ch === ";") && /\s/.test(prev)) { push(spans, base + i, base + text.length, "comment"); break; }
    const rest = text.slice(i);
    let m;
    if ((m = STRING.exec(rest))) { push(spans, base + i, base + i + m[0].length, "string"); i += m[0].length; continue; }
    if ((m = URL_RE.exec(rest))) { push(spans, base + i, base + i + m[0].length, "url"); i += m[0].length; continue; }
    if (/[\w!^~-]/.test(ch) && !/[\w]/.test(prev) || ch === "!" || ch === "^" || ch === "~") {
      if (mode === "klipper" && (m = PIN.exec(rest))) { push(spans, base + i, base + i + m[0].length, "pin"); i += m[0].length; continue; }
      if (!/\w/.test(prev) && (m = NUMBER.exec(rest))) { push(spans, base + i, base + i + m[0].length, "number"); i += m[0].length; continue; }
      if (!/\w/.test(prev) && (m = BOOL.exec(rest))) { push(spans, base + i, base + i + m[0].length, "bool"); i += m[0].length; continue; }
    }
    if (/[A-Za-z_]/.test(ch)) { const w = /^[\w.-]+/.exec(rest)[0]; i += w.length; continue; }   // plain identifier
    i += 1;
  }
  return spans;
}

// Klipper's macro templates use Jinja with "{% %}" statements, "{# #}" comments and SINGLE-brace "{ }" expressions;
// "{{ }}" is accepted too (Moonraker's own templates). ``kind`` is one of the keys below.
const JINJA = {
  stmt: { open: "{%", close: "%}", delim: "jinjaDelim" },
  comment: { open: "{#", close: "#}", delim: "jinjaComment" },
  exprd: { open: "{{", close: "}}", delim: "jinjaDelim" },
  expr: { open: "{", close: "}", delim: "jinjaDelim" },
};

function jinjaKindAt(line, p) {
  const two = line.slice(p, p + 2);
  if (two === "{%") return "stmt";
  if (two === "{#") return "comment";
  if (two === "{{") return "exprd";
  return "expr";
}

/** Index just past the closing delimiter of a construct whose body starts at ``from``, or -1 if it is still open. */
function findClose(line, from, kind) {
  if (kind !== "expr") {
    const at = line.indexOf(JINJA[kind].close, from);
    return at === -1 ? -1 : at + 2;
  }
  let depth = 1;
  for (let i = from; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === "\"" || ch === "'") {                       // skip a string literal
      const q = ch;
      i += 1;
      while (i < line.length && line[i] !== q) { if (line[i] === "\\") i += 1; i += 1; }
    } else if (ch === "{") depth += 1;
    else if (ch === "}") { depth -= 1; if (depth === 0) return i + 1; }
  }
  return -1;
}

/** Highlight one Jinja construct on this line: from ``start`` to ``end`` (``closed``: the closer is at the end). */
function tokenizeJinja(line, start, end, kind, opening, closed) {
  const spans = [];
  const def = JINJA[kind];
  const openLen = opening ? def.open.length : 0;
  const closeLen = closed ? def.close.length : 0;
  const innerFrom = start + openLen;
  const innerTo = end - closeLen;
  if (opening) push(spans, start, innerFrom, def.delim);
  if (kind === "comment") {
    push(spans, innerFrom, innerTo, "jinjaComment");
  } else {
    const text = line.slice(innerFrom, innerTo);
    let i = 0;
    while (i < text.length) {
      const rest = text.slice(i);
      let m;
      if ((m = STRING.exec(rest))) { push(spans, innerFrom + i, innerFrom + i + m[0].length, "string"); i += m[0].length; continue; }
      if ((m = /^[A-Za-z_]\w*/.exec(rest))) {
        const w = m[0];
        const before = text.slice(0, i).trimEnd().slice(-1);
        const isAttr = before === "." && text[i - 1] === ".";
        const after = rest.slice(w.length).trimStart()[0];
        let t = null;
        if (!isAttr && JINJA_KEYWORDS.has(w)) t = "jinjaKeyword";
        else if (!isAttr && JINJA_VARS.has(w)) t = after === "(" ? "jinjaFunc" : "jinjaVar";
        else if (!isAttr && (after === "(" || before === "|")) t = "jinjaFunc";
        push(spans, innerFrom + i, innerFrom + i + w.length, t);
        i += w.length;
        continue;
      }
      if ((m = NUMBER.exec(rest)) && !/\w/.test(text[i - 1] || " ")) { push(spans, innerFrom + i, innerFrom + i + m[0].length, "number"); i += m[0].length; continue; }
      i += 1;
    }
  }
  if (closed) push(spans, innerTo, end, def.delim);
  return spans;
}

const CMD = /^(?:[GMT]\d+(?:\.\d+)?)(?![\w])/i;
const MACRO = /^[A-Za-z_][A-Za-z0-9_]*/;

/** A Jinja-free stretch of G-code. ``ctx.first``: the stretch starts the logical line; ``ctx.gm``: a G/M command was seen. */
function tokenizeGcodeSegment(text, base, ctx) {
  const spans = [];
  let i = 0;
  if (ctx.first) {
    const lead = /^\s*/.exec(text)[0].length;
    i = lead;
    let m;
    if ((m = CMD.exec(text.slice(i)))) { push(spans, base + i, base + i + m[0].length, "gcodeCmd"); i += m[0].length; ctx.gm = true; }
    else if ((m = MACRO.exec(text.slice(i)))) {
      const after = text.slice(i + m[0].length);
      // `NAME` or `NAME key=value`: a Klipper command / macro call (not a stray word followed by a colon etc.)
      if (after === "" || /^\s/.test(after) || after.startsWith("{")) { push(spans, base + i, base + i + m[0].length, "macroName"); i += m[0].length; }
    }
    ctx.first = false;
  }
  while (i < text.length) {
    const rest = text.slice(i);
    const prev = i === 0 ? " " : text[i - 1];
    let m;
    if ((m = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(rest)) && !/\w/.test(prev)) {
      push(spans, base + i, base + i + m[1].length, "gcodeParam");
      push(spans, base + i + m[1].length, base + i + m[0].length, "operator");
      i += m[0].length;
      continue;
    }
    if (ctx.gm && !/\w/.test(prev) && (m = /^([A-Za-z])(-?(?:\d+\.?\d*|\.\d+))(?![\w.])/.exec(rest))) {
      push(spans, base + i, base + i + 1, "gcodeAxis");
      push(spans, base + i + 1, base + i + m[0].length, "number");
      i += m[0].length;
      continue;
    }
    if (ctx.gm && rest.length === 1 && /[A-Za-z]/.test(rest) && !/\w/.test(prev)) {       // "S{bed}": the letter before a Jinja value
      push(spans, base + i, base + i + 1, "gcodeAxis");
      i += 1;
      continue;
    }
    if ((m = STRING.exec(rest))) { push(spans, base + i, base + i + m[0].length, "string"); i += m[0].length; continue; }
    if (!/\w/.test(prev) && (m = NUMBER.exec(rest))) { push(spans, base + i, base + i + m[0].length, "number"); i += m[0].length; continue; }
    if (/[A-Za-z_]/.test(rest[0])) { i += /^[\w.-]+/.exec(rest)[0].length; continue; }
    i += 1;
  }
  return spans;
}

const GCODE_META = /^;\s*(TYPE|LAYER|LAYER_CHANGE|LAYER_COUNT|MESH|FEATURE|HEIGHT|WIDTH|PRINT_START|PRINT_END|EXCLUDE_OBJECT[A-Z_]*)\b/i;

/**
 * G-code (and macro body) text: ``;`` comments, Jinja constructs (possibly spanning lines, tracked in
 * ``state.jinja`` as the construct kind), commands, macro calls and parameters. In plain .gcode files there is no
 * Jinja: braces are ordinary text.
 */
function tokenizeGcodeText(line, state, { macroBody }) {
  const spans = [];
  const ctx = { first: true, gm: false };
  let i = 0;
  let jinja = macroBody ? state.jinja : null;
  while (i < line.length) {
    if (jinja) {
      const end = findClose(line, i, jinja);
      const to = end === -1 ? line.length : end;
      spans.push(...tokenizeJinja(line, i, to, jinja, false, end !== -1));
      i = to;
      if (end !== -1) jinja = null;
      continue;
    }
    const semi = line.indexOf(";", i);
    const brace = macroBody ? line.indexOf("{", i) : -1;
    if (semi !== -1 && (brace === -1 || semi < brace)) {
      if (semi > i) spans.push(...tokenizeGcodeSegment(line.slice(i, semi), i, ctx));
      push(spans, semi, line.length, !macroBody && GCODE_META.test(line.slice(semi)) ? "meta" : "comment");
      i = line.length;
      break;
    }
    if (brace !== -1) {
      if (brace > i) spans.push(...tokenizeGcodeSegment(line.slice(i, brace), i, ctx));
      ctx.first = false;
      const kind = jinjaKindAt(line, brace);
      const openLen = JINJA[kind].open.length;
      const end = findClose(line, brace + openLen, kind);
      const to = end === -1 ? line.length : end;
      spans.push(...tokenizeJinja(line, brace, to, kind, true, end !== -1));
      jinja = end === -1 ? kind : null;
      i = to;
      continue;
    }
    spans.push(...tokenizeGcodeSegment(line.slice(i), i, ctx));
    i = line.length;
  }
  return { spans, jinja };
}

/** A line of ``[section id]`` / ``key: value`` text (also the payload of ``#*#`` auto-save lines). */
function tokenizeIni(line, base, state, { auto }) {
  const spans = [];
  let m;
  if ((m = SECTION.exec(line))) {
    const open = m[1].length;
    const inner = m[2];
    const lead = /^\s*/.exec(inner)[0].length;
    const name = /^\S+/.exec(inner.slice(lead));
    const nameStart = open + 1 + lead;
    push(spans, base + open, base + open + 1, "bracket");
    if (name) {
      push(spans, base + nameStart, base + nameStart + name[0].length, "section");
      const restFrom = nameStart + name[0].length;
      const id = inner.slice(restFrom - (open + 1)).trim();
      if (id) {
        const idStart = base + open + 1 + inner.indexOf(id, restFrom - (open + 1));
        push(spans, idStart, idStart + id.length, name[0] === "gcode_macro" ? "macroName" : "sectionId");
      }
    }
    const close = m[0].length - 1;
    push(spans, base + close, base + close + 1, "bracket");
    const tail = line.slice(m[0].length);
    const ts = /^\s*[#;]/.exec(tail);
    if (ts) push(spans, base + m[0].length + ts[0].length - 1, base + line.length, "comment");
    return { spans, kind: "section" };
  }
  if ((m = KEY.exec(line))) {
    const key = m[1];
    push(spans, base, base + key.length, /^variable_/i.test(key) ? "variableKey" : "key");
    push(spans, base + key.length + m[2].length, base + m[0].length, "operator");
    const valueFrom = m[0].length;
    const value = line.slice(valueFrom);
    if (GCODE_KEYS.test(key)) {
      const g = tokenizeGcodeText(value, state, { macroBody: true });
      for (const s of g.spans) spans.push({ ...s, from: s.from + base + valueFrom, to: s.to + base + valueFrom });
      return { spans, kind: "gcodeKey", jinja: g.jinja };
    }
    spans.push(...tokenizeValue(value, base + valueFrom, state.mode));
    return { spans, kind: "key" };
  }
  void auto;
  return { spans, kind: "other" };
}

/**
 * Tokenize one line. Returns ``{spans, state}``: spans are sorted, non-overlapping and typed; text between
 * them is plain. ``state`` is a fresh object (never mutated), safe to keep per line.
 */
export function tokenizeLine(line, state) {
  const next = { ...state };
  const spans = [];
  const mode = state.mode;

  if (mode === "gcode") {
    const r = tokenizeGcodeText(line, state, { macroBody: false });
    next.jinja = r.jinja;
    return { spans: r.spans, state: next };
  }
  if (mode !== "klipper" && mode !== "moonraker") return { spans, state: next };

  if (!line.trim()) return { spans, state: next };
  if (SAVE_MARKER.test(line)) {
    push(spans, 0, line.length, "meta");
    next.saveConfig = true;
    next.gcodeBlock = false;
    next.jinja = null;
    return { spans, state: next };
  }
  if (next.saveConfig && line.startsWith("#*#")) {
    push(spans, 0, 3, "autosave");
    const payload = line.slice(3);
    const lead = /^\s*/.exec(payload)[0].length;
    const r = tokenizeIni(payload.slice(lead), 3 + lead, state, { auto: true });
    spans.push(...(r.kind === "other" ? [{ from: 3, to: line.length, type: "autosave" }] : r.spans));
    return { spans, state: next };
  }
  if (next.gcodeBlock) {
    if (/^\s/.test(line)) {
      const r = tokenizeGcodeText(line, state, { macroBody: true });
      next.jinja = r.jinja;
      return { spans: r.spans, state: next };
    }
    if (/^[#;]/.test(line)) { push(spans, 0, line.length, "comment"); return { spans, state: next }; }
    next.gcodeBlock = false;
    next.jinja = null;
  }
  if (/^\s*[#;]/.test(line)) { push(spans, 0, line.length, "comment"); return { spans, state: next }; }
  if (/^\s/.test(line)) {                                    // continuation of a multi-line value
    return { spans: tokenizeValue(line, 0, mode), state: next };
  }
  const r = tokenizeIni(line, 0, state, { auto: false });
  if (r.kind === "section") next.gcodeBlock = false;
  if (r.kind === "gcodeKey") { next.gcodeBlock = true; next.jinja = r.jinja || null; }
  if (r.kind === "other") push(r.spans, 0, line.length, "invalid");
  return { spans: r.spans, state: next };
}

/** Tokenize a whole text; returns an array (one entry per line) of ``{spans}``. Used by tests and the outline. */
export function tokenizeText(text, mode) {
  let state = startState(mode);
  return text.split("\n").map((line) => {
    const r = tokenizeLine(line, state);
    state = r.state;
    return { line, spans: r.spans };
  });
}

// ── Outline and folding ────────────────────────────────────────────────────────────────────────────────────
/** Jump targets: config sections (including the auto-saved ones) or Markdown headings. */
export function outlineOf(text, mode) {
  const out = [];
  const lines = text.split("\n");
  if (mode === "klipper" || mode === "moonraker") {
    let auto = false;
    lines.forEach((line, i) => {
      if (SAVE_MARKER.test(line)) { auto = true; out.push({ line: i, name: "SAVE_CONFIG (auto-saved values)", kind: "autosave", depth: 0 }); return; }
      const body = auto && line.startsWith("#*#") ? line.slice(3) : line;
      const m = /^\[([^\]]+)\]/.exec(body.trimStart());
      if (m && (!auto || line.startsWith("#*#") || !line.startsWith(" "))) out.push({ line: i, name: m[1].trim(), kind: auto ? "auto" : "section", depth: auto ? 1 : 0 });
    });
  } else if (mode === "markdown") {
    let fence = false;
    lines.forEach((line, i) => {
      if (/^```/.test(line)) { fence = !fence; return; }
      const m = !fence && /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
      if (m) out.push({ line: i, name: m[2], kind: "heading", depth: m[1].length - 1 });
    });
  }
  return out;
}

/** Foldable block starting on line ``i``: ``{from: i, to: lastLine}`` (0-based, ``to > from``) or null. */
export function foldRange(lines, i, mode) {
  const line = lines[i] ?? "";
  const last = lines.length - 1;
  const trimEnd = (end) => { let e = end; while (e > i && !lines[e].trim()) e -= 1; return e; };
  if (mode === "klipper" || mode === "moonraker") {
    const isHeader = (l) => /^\[[^\]]+\]/.test(l) || /^#\*#\s*\[[^\]]+\]/.test(l) || SAVE_MARKER.test(l);
    if (isHeader(line) && !SAVE_MARKER.test(line)) {
      let e = i + 1;
      while (e <= last && !isHeader(lines[e])) e += 1;
      const end = trimEnd(e - 1);
      return end > i ? { from: i, to: end } : null;
    }
    const m = KEY.exec(line);
    if (m && !/^\s/.test(line) && GCODE_KEYS.test(m[1])) {
      let e = i + 1;
      while (e <= last && (/^\s/.test(lines[e]) || !lines[e].trim() || /^[#;]/.test(lines[e]))) e += 1;
      const end = trimEnd(e - 1);
      return end > i ? { from: i, to: end } : null;
    }
    return null;
  }
  if (mode === "markdown") {
    const m = /^(#{1,6})\s/.exec(line);
    if (!m) return null;
    let e = i + 1;
    while (e <= last && !(/^(#{1,6})\s/.test(lines[e]) && /^(#+)/.exec(lines[e])[1].length <= m[1].length)) e += 1;
    const end = trimEnd(e - 1);
    return end > i ? { from: i, to: end } : null;
  }
  return null;
}

export const SHORTCUTS = [
  ["Ctrl/Cmd + S", "Save"],
  ["Ctrl/Cmd + Shift + S", "Save and restart (Klipper config)"],
  ["Ctrl/Cmd + F", "Find (Enter: next, Shift+Enter: previous)"],
  ["Ctrl/Cmd + G", "Find next"],
  ["Ctrl/Cmd + Alt + F", "Find and replace"],
  ["Ctrl/Cmd + Alt + G", "Go to line"],
  ["Ctrl/Cmd + Alt + O", "Outline: jump to a section or heading"],
  ["Ctrl + Shift + [ / ]  (Cmd + Alt on Mac)", "Fold / unfold the block at the cursor"],
  ["Ctrl + Alt + [ / ]", "Fold all / unfold all"],
  ["Ctrl/Cmd + Z / Shift + Z", "Undo / redo"],
  ["Tab / Shift + Tab", "Indent / outdent"],
  ["Ctrl/Cmd + /", "Toggle comment"],
  ["Esc", "Close panels, then the editor"],
  ["F1", "This help"],
];
