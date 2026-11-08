import { test } from "node:test";
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";

// Loads the real CodeMirror adapter (catches tag/definition errors that only show up in the browser) and
// checks that the stream language produces the node names the theme styles.
const { languageFor, themeExtensions } = await import("./cmLanguages.js");

function nodeNames(doc, mode) {
  const state = EditorState.create({ doc, extensions: languageFor(mode) });
  const tree = ensureSyntaxTree(state, doc.length, 5000) || syntaxTree(state);
  const out = [];
  tree.iterate({ enter: (n) => { if (n.from < n.to) out.push([n.name, doc.slice(n.from, n.to)]); } });
  return out;
}

test("klipper config: the stream language yields typed nodes for each piece", () => {
  const doc = "[gcode_macro START]\nvariable_x: 1\ngcode:\n    G28\n    {% if x %}\n    M117 {x}\n    {% endif %}\n";
  const names = nodeNames(doc, "klipper").map(([n, text]) => `${n}:${text}`);
  assert.ok(names.includes("section:gcode_macro"), names.join("|"));
  assert.ok(names.includes("macroName:START"));
  assert.ok(names.includes("variableKey:variable_x"));
  assert.ok(names.includes("gcodeCmd:G28"));
  assert.ok(names.includes("jinjaKeyword:if"));
  assert.ok(names.includes("gcodeCmd:M117"));
});

test("gcode mode and plain modes build without error", () => {
  assert.ok(nodeNames("G1 X1 Y2 E0.3 ; hi\n", "gcode").some(([n]) => n === "gcodeCmd"));
  for (const mode of ["json", "markdown", "text", "moonraker"]) {
    assert.doesNotThrow(() => EditorState.create({ doc: "x", extensions: languageFor(mode) }), mode);
  }
});

test("themes build for every app theme in light and dark", () => {
  for (const name of ["classic", "workshop", "blueprint", "creme"]) {
    for (const dark of [true, false]) assert.ok(themeExtensions(name, dark).length >= 2, `${name}/${dark}`);
  }
});

test("a long config with a SAVE_CONFIG block parses", () => {
  const body = Array.from({ length: 300 }, (_, i) => `[stepper_${i}]\nstep_pin: PA${i % 16}\n`).join("");
  const doc = `${body}#*# <---- SAVE_CONFIG ---->\n#*# [probe]\n#*# z_offset = 1.2\n`;
  const names = nodeNames(doc, "klipper").map(([n]) => n);
  assert.ok(names.includes("meta") && names.includes("autosave") && names.includes("pin"));
});
