import { test } from "node:test";
import assert from "node:assert/strict";
import { modeForFile, startState, tokenizeLine, tokenizeText, outlineOf, foldRange } from "./syntax.js";

// the typed pieces of a line as [text, type] pairs (plain text between them is left out)
function pieces(line, mode = "klipper", state = startState(mode)) {
  const r = tokenizeLine(line, state);
  return { toks: r.spans.map((s) => [line.slice(s.from, s.to), s.type]), state: r.state };
}
const types = (line, mode, state) => pieces(line, mode, state).toks;

test("mode by file name", () => {
  assert.equal(modeForFile("printer.cfg"), "klipper");
  assert.equal(modeForFile("config/macros.CFG"), "klipper");
  assert.equal(modeForFile("moonraker.conf"), "moonraker");
  assert.equal(modeForFile("crowsnest.conf"), "moonraker");
  assert.equal(modeForFile("a.gcode"), "gcode");
  assert.equal(modeForFile("data.json"), "json");
  assert.equal(modeForFile("README.md"), "markdown");
  assert.equal(modeForFile("notes.txt"), "text");
});

test("klipper: sections, ids and macro names", () => {
  assert.deepEqual(types("[stepper_x]"), [["[", "bracket"], ["stepper_x", "section"], ["]", "bracket"]]);
  assert.deepEqual(types("[gcode_macro START_PRINT]"),
    [["[", "bracket"], ["gcode_macro", "section"], ["START_PRINT", "macroName"], ["]", "bracket"]]);
  assert.deepEqual(types("[heater_generic chamber]  # note"),
    [["[", "bracket"], ["heater_generic", "section"], ["chamber", "sectionId"], ["]", "bracket"], ["# note", "comment"]]);
});

test("klipper: comments, keys, numbers, pins, booleans, trailing comments", () => {
  assert.deepEqual(types("# a comment"), [["# a comment", "comment"]]);
  assert.deepEqual(types("; also a comment"), [["; also a comment", "comment"]]);
  assert.deepEqual(types("step_pin: PF13"), [["step_pin", "key"], [":", "operator"], ["PF13", "pin"]]);
  assert.deepEqual(types("dir_pin: !PF12"), [["dir_pin", "key"], [":", "operator"], ["!PF12", "pin"]]);
  assert.deepEqual(types("serial: /dev/serial/by-id/usb-Klipper_stm32-if00"), [["serial", "key"], [":", "operator"]]);
  assert.deepEqual(types("pin: host:gpio20"), [["pin", "key"], [":", "operator"], ["host:gpio20", "pin"]]);
  assert.deepEqual(types("max_velocity = 300"), [["max_velocity", "key"], ["=", "operator"], ["300", "number"]]);
  assert.deepEqual(types("position_min: -2.5  # lower"), [["position_min", "key"], [":", "operator"], ["-2.5", "number"], ["# lower", "comment"]]);
  assert.deepEqual(types("verbose: True"), [["verbose", "key"], [":", "operator"], ["True", "bool"]]);
  assert.deepEqual(types("variable_bed: 60"), [["variable_bed", "variableKey"], [":", "operator"], ["60", "number"]]);
  assert.deepEqual(types("description: say \"hi # not a comment\""), [["description", "key"], [":", "operator"], ["\"hi # not a comment\"", "string"]]);
});

test("klipper: a '#' without whitespace before it is not a trailing comment", () => {
  assert.equal(types("rotation_distance: 40#x").some(([, t]) => t === "comment"), false);
});

test("klipper: gcode: block with Jinja, commands, macros and parameters", () => {
  const text = [
    "[gcode_macro START_PRINT]",
    "variable_t: 200",
    "gcode:",
    "    {% set bed = params.BED|default(60)|float %}",
    "    M140 S{bed}",
    "    G28",
    "    SET_HEATER_TEMPERATURE HEATER=extruder TARGET={printer.configfile.settings.extruder.max_temp}",
    "    {action_respond_info(\"hi\")}",
    "    ; plain gcode comment",
    "",
    "[printer]",
  ].join("\n");
  const toks = tokenizeText(text, "klipper").map((l) => l.spans.map((s) => [l.line.slice(s.from, s.to), s.type]));
  assert.deepEqual(toks[2], [["gcode", "key"], [":", "operator"]]);
  assert.deepEqual(toks[3], [["{%", "jinjaDelim"], ["set", "jinjaKeyword"], ["params", "jinjaVar"], ["default", "jinjaFunc"],
    ["60", "number"], ["float", "jinjaFunc"], ["%}", "jinjaDelim"]]);
  assert.deepEqual(toks[4], [["M140", "gcodeCmd"], ["S", "gcodeAxis"], ["{", "jinjaDelim"], ["}", "jinjaDelim"]]);   // Klipper: single-brace expressions
  assert.deepEqual(toks[5], [["G28", "gcodeCmd"]]);
  assert.deepEqual(toks[6].slice(0, 6), [["SET_HEATER_TEMPERATURE", "macroName"], ["HEATER", "gcodeParam"], ["=", "operator"],
    ["TARGET", "gcodeParam"], ["=", "operator"], ["{", "jinjaDelim"]]);
  assert.ok(toks[6].some(([t, ty]) => t === "printer" && ty === "jinjaVar"));
  assert.ok(toks[7].some(([t, ty]) => t === "action_respond_info" && ty === "jinjaFunc"));
  assert.deepEqual(toks[8], [["; plain gcode comment", "comment"]]);
  assert.deepEqual(toks[10], [["[", "bracket"], ["printer", "section"], ["]", "bracket"]]);   // block ended at the next section
});

test("klipper: braces inside strings do not end an expression; {# #} may span lines", () => {
  const st = { ...startState("klipper"), gcodeBlock: true };
  const t = types("    G1 X{x[\"a}\"]} Y1", "klipper", st);
  assert.deepEqual(t.map((x) => x[1]), ["gcodeCmd", "gcodeAxis", "jinjaDelim", "string", "jinjaDelim", "gcodeAxis", "number"]);
  const a = pieces("    {# multi", "klipper", st);
  assert.equal(a.state.jinja, "comment");
  const b = pieces("    line #}", "klipper", a.state);
  assert.equal(b.state.jinja, null);
  assert.deepEqual(b.toks.at(-1), ["#}", "jinjaComment"]);
});

test("klipper: Jinja markers inside a macro are colored by kind", () => {
  const st = { ...startState("klipper"), gcodeBlock: true };
  const t = types("    {% if printer.toolhead.homed_axes != \"xyz\" %}", "klipper", st);
  assert.deepEqual(t.slice(0, 3), [["{%", "jinjaDelim"], ["if", "jinjaKeyword"], ["printer", "jinjaVar"]]);
  assert.ok(t.some(([x, y]) => x === "\"xyz\"" && y === "string"));
  assert.equal(t.at(-1)[1], "jinjaDelim");
  const e = types("    {{ params.X|default(1) }}", "klipper", st);
  assert.deepEqual(e.slice(0, 2), [["{{", "jinjaDelim"], ["params", "jinjaVar"]]);
  assert.deepEqual(types("    {# a note #}", "klipper", st), [["{#", "jinjaComment"], [" a note ", "jinjaComment"], ["#}", "jinjaComment"]]);
});

test("klipper: a Jinja block spanning lines keeps its state", () => {
  const st = { ...startState("klipper"), gcodeBlock: true };
  const a = pieces("    {% set x = 1", "klipper", st);
  assert.equal(a.state.jinja, "stmt");
  const b = pieces("      + 2 %}", "klipper", a.state);
  assert.equal(b.state.jinja, null);
  assert.ok(b.toks.some(([t, ty]) => t === "%}" && ty === "jinjaDelim"));
  assert.ok(b.toks.some(([t, ty]) => t === "2" && ty === "number"));
});

test("klipper: *_gcode keys open a block as well", () => {
  const r = pieces("pause_gcode:", "klipper");
  assert.equal(r.state.gcodeBlock, true);
  assert.equal(pieces("max_velocity: 5", "klipper").state.gcodeBlock, false);
  const inBlock = pieces("rename_existing: BASE_PAUSE", "klipper", r.state);
  assert.equal(inBlock.state.gcodeBlock, false);          // a column-0 key ends the block
});

test("klipper: SAVE_CONFIG block", () => {
  const text = [
    "[printer]", "#*# <---- SAVE_CONFIG ---->", "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.", "#*#",
    "#*# [stepper_z]", "#*# position_endstop = 0.5", "#*# [probe]", "#*# z_offset = -1.25",
  ].join("\n");
  const r = tokenizeText(text, "klipper").map((l) => l.spans.map((s) => [l.line.slice(s.from, s.to), s.type]));
  assert.deepEqual(r[1], [["#*# <---- SAVE_CONFIG ---->", "meta"]]);
  assert.equal(r[2][0][1], "autosave");
  assert.deepEqual(r[4].slice(0, 4), [["#*#", "autosave"], ["[", "bracket"], ["stepper_z", "section"], ["]", "bracket"]]);
  assert.deepEqual(r[5].map((x) => x[1]), ["autosave", "key", "operator", "number"]);
  assert.equal(r[7].at(-1)[0], "-1.25");
  // before the marker "#*#" is just a comment
  assert.deepEqual(types("#*# stray"), [["#*# stray", "comment"]]);
});

test("klipper: unknown lines are flagged invalid", () => {
  assert.deepEqual(types("this is not config"), [["this is not config", "invalid"]]);
  assert.deepEqual(types(""), []);
});

test("moonraker mode: urls and no pin coloring", () => {
  assert.deepEqual(types("origin: https://github.com/Arksine/moonraker.git", "moonraker"), [["origin", "key"], [":", "operator"], ["https://github.com/Arksine/moonraker.git", "url"]]);
  assert.deepEqual(types("pin: PA5", "moonraker"), [["pin", "key"], [":", "operator"]]);
  assert.deepEqual(types("port: 7125", "moonraker").at(-1), ["7125", "number"]);
  assert.deepEqual(types("[update_manager client mainsail]", "moonraker").map((x) => x[1]), ["bracket", "section", "sectionId", "bracket"]);
});

test("gcode mode: commands, axes, comments, slicer markers, macro calls", () => {
  assert.deepEqual(types("G1 X10.5 Y-3 E0.4 F1800 ; move", "gcode"),
    [["G1", "gcodeCmd"], ["X", "gcodeAxis"], ["10.5", "number"], ["Y", "gcodeAxis"], ["-3", "number"], ["E", "gcodeAxis"], ["0.4", "number"],
      ["F", "gcodeAxis"], ["1800", "number"], ["; move", "comment"]]);
  assert.deepEqual(types("M104 S215", "gcode"), [["M104", "gcodeCmd"], ["S", "gcodeAxis"], ["215", "number"]]);
  assert.deepEqual(types(";TYPE:WALL-OUTER", "gcode"), [[";TYPE:WALL-OUTER", "meta"]]);
  assert.deepEqual(types(";LAYER_CHANGE", "gcode"), [[";LAYER_CHANGE", "meta"]]);
  assert.deepEqual(types("; layer_height = 0.2", "gcode"), [["; layer_height = 0.2", "comment"]]);
  assert.deepEqual(types("SET_PRESSURE_ADVANCE ADVANCE=0.04", "gcode"), [["SET_PRESSURE_ADVANCE", "macroName"], ["ADVANCE", "gcodeParam"], ["=", "operator"], ["0.04", "number"]]);
  assert.deepEqual(types("START_PRINT BED=60 EXTRUDER=215", "gcode").map((x) => x[1]), ["macroName", "gcodeParam", "operator", "number", "gcodeParam", "operator", "number"]);
  assert.deepEqual(types("", "gcode"), []);
});

test("plain modes produce no spans", () => {
  assert.deepEqual(types("{\"a\": 1}", "json"), []);
  assert.deepEqual(types("# Title", "markdown"), []);
});

test("states are independent: re-tokenizing from a saved state gives the same result", () => {
  const lines = ["[gcode_macro A]", "gcode:", "    G28", "[x]"];
  let s = startState("klipper");
  const states = [];
  for (const l of lines) { s = tokenizeLine(l, s).state; states.push(s); }
  assert.equal(states[1].gcodeBlock, true);
  assert.equal(states[3].gcodeBlock, false);
  assert.equal(states[1].gcodeBlock, true);                 // earlier states were not mutated by later lines
  assert.deepEqual(tokenizeLine("    G28", states[1]).spans.map((x) => x.type), ["gcodeCmd"]);
});

test("outline: config sections incl. auto-saved ones, markdown headings", () => {
  const cfg = "[printer]\nx: 1\n\n[gcode_macro A]\ngcode:\n  G28\n#*# <---- SAVE_CONFIG ---->\n#*# [probe]\n#*# z_offset = 1\n";
  assert.deepEqual(outlineOf(cfg, "klipper").map((o) => [o.line, o.name, o.kind]), [
    [0, "printer", "section"], [3, "gcode_macro A", "section"], [6, "SAVE_CONFIG (auto-saved values)", "autosave"], [7, "probe", "auto"]]);
  const md = "# A\n```\n# not a heading\n```\n## B\ntext";
  assert.deepEqual(outlineOf(md, "markdown").map((o) => [o.line, o.name, o.depth]), [[0, "A", 0], [4, "B", 1]]);
  assert.deepEqual(outlineOf("G28", "gcode"), []);
});

test("folding: sections, gcode blocks, markdown headings", () => {
  const cfg = ["[printer]", "a: 1", "b: 2", "", "[gcode_macro M]", "gcode:", "  G28", "  ; c", "", "  G1 X1", "", "[probe]", "z: 1"];
  assert.deepEqual(foldRange(cfg, 0, "klipper"), { from: 0, to: 2 });            // trailing blank line excluded
  assert.deepEqual(foldRange(cfg, 4, "klipper"), { from: 4, to: 9 });
  assert.deepEqual(foldRange(cfg, 5, "klipper"), { from: 5, to: 9 });            // the gcode: value block
  assert.equal(foldRange(cfg, 1, "klipper"), null);
  assert.equal(foldRange(cfg, 12, "klipper"), null);                              // single-line section: nothing to fold
  assert.equal(foldRange(["[a]", "[b]"], 0, "klipper"), null);
  const md = ["# A", "text", "## B", "more", "# C", "end"];
  assert.deepEqual(foldRange(md, 0, "markdown"), { from: 0, to: 3 });
  assert.deepEqual(foldRange(md, 2, "markdown"), { from: 2, to: 3 });
  assert.equal(foldRange(md, 1, "markdown"), null);
  assert.equal(foldRange(["G28"], 0, "gcode"), null);
});
