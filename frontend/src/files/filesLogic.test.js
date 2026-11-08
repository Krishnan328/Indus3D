import { test } from "node:test";
import assert from "node:assert/strict";
import {
  joinPath, parentPath, baseName, extOf, isWithin, breadcrumbs, validateName, uniqueName,
  formatBytes, formatDuration, formatFilament, formatClock, fileKind, isEditable, canPrint,
  isBackupName, isTempName, isRolledLog, applyFilters, DEFAULT_FILTERS,
  sortEntries, pickThumbnail, fuzzyScore, fuzzyFilter, matchesSearch, queueTotals, moveItem, apiErrorMessage, parseGcodeLayers,
} from "./filesLogic.js";

test("path joining and splitting", () => {
  assert.equal(joinPath("a", "b/c", "", "d.gcode"), "a/b/c/d.gcode");
  assert.equal(joinPath("", "x"), "x");
  assert.equal(joinPath("a/", "/b", "./c"), "a/b/c");
  assert.equal(joinPath(), "");
  assert.equal(parentPath("a/b/c.gcode"), "a/b");
  assert.equal(parentPath("c.gcode"), "");
  assert.equal(baseName("a/b/c.gcode"), "c.gcode");
  assert.equal(baseName("c.gcode"), "c.gcode");
  assert.equal(extOf("a/B.GCode"), "gcode");
  assert.equal(extOf("Makefile"), "");
  assert.ok(isWithin("a/b", "a") && isWithin("a", "a") && isWithin("x", "") && !isWithin("ab", "a"));
});

test("breadcrumbs", () => {
  assert.deepEqual(breadcrumbs("gcodes", ""), [{ label: "gcodes", path: "" }]);
  assert.deepEqual(breadcrumbs("gcodes", "a/b"), [
    { label: "gcodes", path: "" }, { label: "a", path: "a" }, { label: "b", path: "a/b" }]);
});

test("name validation mirrors the server", () => {
  assert.equal(validateName("good name.gcode"), null);
  for (const bad of ["", " ", " a", "a ", ".", "..", "a/b", "a\\b", "a\x00b", "x".repeat(256), null]) {
    assert.ok(validateName(bad), `should reject ${JSON.stringify(bad)}`);
  }
});

test("unique copy names", () => {
  assert.equal(uniqueName("a.gcode", new Set()), "a.gcode");
  assert.equal(uniqueName("a.gcode", new Set(["a.gcode"])), "a (copy).gcode");
  assert.equal(uniqueName("a.gcode", new Set(["a.gcode", "a (copy).gcode"])), "a (copy 2).gcode");
  assert.equal(uniqueName("noext", new Set(["noext"])), "noext (copy)");
});

test("formatting", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.0 MB");
  assert.equal(formatBytes(3 * 1024 ** 3), "3.0 GB");
  assert.equal(formatBytes(null), "");
  assert.equal(formatDuration(45), "45s");
  assert.equal(formatDuration(600), "10m");
  assert.equal(formatDuration(3720), "1h 02m");
  assert.equal(formatDuration(200000), "2d 7h");
  assert.equal(formatDuration(0), "");
  assert.equal(formatFilament(5400, 16.2), "5.4 m · 16.2 g");
  assert.equal(formatFilament(null, 120), "120 g");
});

test("file kinds", () => {
  assert.equal(fileKind("a.gcode"), "gcode");
  assert.equal(fileKind("a.PNG"), "image");
  assert.equal(fileKind("t.mp4"), "video");
  assert.equal(fileKind("README.md"), "markdown");
  assert.equal(fileKind("printer.cfg"), "text");
  assert.equal(fileKind("README"), "text");
  assert.equal(fileKind("x.zip"), "archive");
  assert.equal(fileKind("x.bin"), "other");
  assert.ok(isEditable("printer.cfg") && isEditable("a.gcode") && !isEditable("a.png"));
  assert.ok(canPrint("a.gcode") && !canPrint("a.ufp") && !canPrint("a.cfg"));
});

test("name classes for the filters", () => {
  for (const n of ["printer-20240101_120000.cfg", "moonraker.conf.bkp", "crowsnest.conf.bak", "printer.cfg~", "a.cfg.orig"]) assert.ok(isBackupName(n), n);
  for (const n of ["printer.cfg", "macros.cfg", "moonraker.conf"]) assert.ok(!isBackupName(n), n);
  for (const n of ["a.gcode.part", "x.tmp", ".tmp_upload", ".indus3d-zip-1-ab.zip"]) assert.ok(isTempName(n), n);
  assert.ok(!isTempName("template.gcode"));
  for (const n of ["klippy.log.2024-01-01", "moonraker.log.1", "klippy.log.2024-01-01.gz", "x.log.gz"]) assert.ok(isRolledLog(n), n);
  assert.ok(!isRolledLog("klippy.log"));
});

test("applyFilters", () => {
  const e = [
    { name: ".thumbs", type: "dir" }, { name: "sub", type: "dir" },
    { name: ".hidden.gcode", type: "file" }, { name: "a.gcode", type: "file", meta: { print_start_time: 5 } },
    { name: "b.gcode", type: "file" }, { name: "printer-20240101_120000.cfg", type: "file" },
    { name: "x.part", type: "file" }, { name: "klippy.log.1", type: "file" }, { name: "klippy.log", type: "file" },
  ];
  const names = (f) => applyFilters(e, f).map((x) => x.name);
  assert.deepEqual(names(DEFAULT_FILTERS), ["sub", "a.gcode", "b.gcode", "klippy.log"]);
  assert.deepEqual(names({ ...DEFAULT_FILTERS, printed: false }), ["sub", "b.gcode", "klippy.log"]);
  assert.equal(names({ hidden: true, backups: true, temp: true, logs: true, printed: true }).length, e.length);
  assert.ok(names({ ...DEFAULT_FILTERS, hidden: true }).includes(".thumbs"));
});

test("sorting: folders first, missing values last, numeric aware names", () => {
  const e = [
    { name: "b.gcode", type: "file", size: 5, modified: 3, meta: { slicer: "Cura", estimated_time: 100, layer_height: 0.2, first_layer_extr_temp: 215 } },
    { name: "a10.gcode", type: "file", size: 9, modified: 1, meta: { slicer: "Prusa", estimated_time: 50, layer_height: 0.12 } },
    { name: "a2.gcode", type: "file", size: 1, modified: 2 },
    { name: "zdir", type: "dir", modified: 9 },
    { name: "adir", type: "dir", modified: 1 },
  ];
  const order = (k, d) => sortEntries(e, k, d).map((x) => x.name);
  assert.deepEqual(order("name", "asc"), ["adir", "zdir", "a2.gcode", "a10.gcode", "b.gcode"]);
  assert.deepEqual(order("name", "desc"), ["zdir", "adir", "b.gcode", "a10.gcode", "a2.gcode"]);
  assert.deepEqual(order("size", "asc"), ["adir", "zdir", "a2.gcode", "b.gcode", "a10.gcode"]);
  assert.deepEqual(order("estimated_time", "asc"), ["adir", "zdir", "a10.gcode", "b.gcode", "a2.gcode"]);
  assert.deepEqual(order("estimated_time", "desc"), ["adir", "zdir", "b.gcode", "a10.gcode", "a2.gcode"]);   // a2 has none: still last
  assert.deepEqual(order("layer_height", "asc").slice(2), ["a10.gcode", "b.gcode", "a2.gcode"]);
  assert.deepEqual(order("slicer", "asc").slice(2), ["b.gcode", "a10.gcode", "a2.gcode"]);
  assert.deepEqual(order("modified", "desc").slice(2), ["b.gcode", "a2.gcode", "a10.gcode"]);
  assert.deepEqual(order("temps", "desc").slice(2), ["b.gcode", "a2.gcode", "a10.gcode"]);   // ties by name
  const before = e.map((x) => x.name);
  sortEntries(e, "size");
  assert.deepEqual(e.map((x) => x.name), before);                                                          // input untouched
});

test("fuzzy scoring prefers contiguous, name and word-start matches", () => {
  assert.equal(fuzzyScore("xyz", "benchy.gcode"), -1);
  assert.ok(fuzzyScore("bnc", "benchy.gcode") >= 0);
  assert.ok(fuzzyScore("bench", "benchy.gcode") > fuzzyScore("bench", "b_e_n_c_h.gcode"));
  assert.ok(fuzzyScore("pa", "calibration/pa_test.gcode") > fuzzyScore("pa", "papers/other_thing.gcode") - 100);
  assert.equal(fuzzyScore("", "anything"), 0);
  assert.ok(fuzzyScore("B E N", "benchy.gcode") >= 0);          // whitespace in the query is ignored
  assert.ok(fuzzyScore("BENCH", "benchy.gcode") >= 0);          // case-insensitive
});

test("fuzzyFilter ranks and limits", () => {
  const files = ["calibration/flow_cube.gcode", "calibration/pa_test.gcode", "benchy.gcode", "archive/benchy_old.gcode", "x.gcode"];
  assert.deepEqual(fuzzyFilter("benchy", files).slice(0, 2), ["benchy.gcode", "archive/benchy_old.gcode"]);
  assert.deepEqual(fuzzyFilter("flowcube", files), ["calibration/flow_cube.gcode"]);
  assert.equal(fuzzyFilter("", files, (x) => x, 2).length, 2);
  assert.equal(fuzzyFilter("zzz", files).length, 0);
  assert.deepEqual(fuzzyFilter("pa", [{ p: "pa.gcode" }, { p: "zz" }], (x) => x.p).map((x) => x.p), ["pa.gcode"]);
});

test("live search needs every term", () => {
  assert.ok(matchesSearch("Benchy_PLA_0.2.gcode", "benchy pla"));
  assert.ok(!matchesSearch("Benchy.gcode", "benchy pla"));
  assert.ok(matchesSearch("a.gcode", "  "));
});

test("queue totals, ETA and missing metadata", () => {
  const jobs = [
    { meta: { estimated_time: 100, filament_total: 1000, filament_weight_total: 3 } },
    { meta: { estimated_time: 200, filament_total: 500 } },
  ];
  const t = queueTotals(jobs, 50, 1000);
  assert.deepEqual([t.count, t.timeS, t.filamentMm, t.filamentG, t.missing, t.finishTs], [2, 300, 1500, 3, 0, 1350]);
  const u = queueTotals([...jobs, { meta: {} }], 0, 0);
  assert.equal(u.missing, 1);
  assert.equal(u.finishTs, null);
  assert.equal(queueTotals([], 10, 0).finishTs, null);
  assert.equal(queueTotals([{}], 0, 0).missing, 1);
});

test("moveItem", () => {
  assert.deepEqual(moveItem(["a", "b", "c", "d"], 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveItem(["a", "b", "c", "d"], 3, 0), ["d", "a", "b", "c"]);
  const same = ["a", "b"];
  assert.equal(moveItem(same, 1, 1), same);
  assert.equal(moveItem(same, 5, 0), same);
});

test("api error messages", () => {
  assert.equal(apiErrorMessage(501, { unsupported: true }), "Not available on this Moonraker");
  assert.equal(apiErrorMessage(409, { code: "busy", error: "x is being printed" }), "x is being printed");
  assert.equal(apiErrorMessage(502, {}), "Moonraker is not reachable");
  assert.equal(apiErrorMessage(429, {}), "Too many requests: slow down a little");
  assert.equal(apiErrorMessage(400, { error: "bad" }), "bad");
  assert.equal(apiErrorMessage(500, {}), "HTTP 500");
});

test("gcode layer parser: absolute extrusion, layers, bounds", () => {
  const g = [
    "G90", "M82", "G28", "G92 E0",
    "G1 Z0.2 F300", "G1 X10 Y10 F3000", "G1 X20 Y10 E1 F1200", "G1 X20 Y20 E2",
    "G1 Z0.4", "G1 X10 Y20", "G1 X10 Y10 E3 ; comment", "G1 X0 Y0 E3",   // last move: no E increase -> travel
  ].join("\n");
  const r = parseGcodeLayers(g);
  assert.equal(r.layers.length, 2);
  assert.equal(r.layers[0].z, 0.2);
  assert.deepEqual(r.layers[0].segs, [10, 10, 20, 10, 20, 10, 20, 20]);
  assert.deepEqual(r.layers[1].segs, [10, 20, 10, 10]);
  assert.deepEqual(r.bounds, { minX: 10, maxX: 20, minY: 10, maxY: 20 });
  assert.equal(r.truncated, false);
});

test("gcode layer parser: relative extrusion, relative moves, G92 reset, truncation", () => {
  const r = parseGcodeLayers(["M83", "G1 X5 Y5", "G1 X10 E0.5", "G91", "G1 X5 E0.5", "G90", "G92 E0", "M82", "G1 X0 E0.1"].join("\n"));
  assert.deepEqual(r.layers[0].segs, [5, 5, 10, 5, 10, 5, 15, 5, 15, 5, 0, 5]);
  const many = Array.from({ length: 20 }, (_, i) => `G1 X${i + 1} E${i + 1}`).join("\n");
  const t = parseGcodeLayers(many, { maxSegments: 5 });
  assert.equal(t.truncated, true);
  assert.equal(t.layers[0].segs.length, 20);
  assert.deepEqual(parseGcodeLayers("").bounds, { minX: 0, maxX: 1, minY: 0, maxY: 1 });
});

test("thumbnail choice", () => {
  const t = [{ width: 32, height: 32, path: "s" }, { width: 300, height: 300, path: "l" }, { width: 100, height: 100, path: "m" }];
  assert.equal(pickThumbnail(t, 64).path, "m");
  assert.equal(pickThumbnail(t, 200).path, "l");
  assert.equal(pickThumbnail(t, 1000).path, "l");               // nothing big enough: the largest available
  assert.equal(pickThumbnail(t, 10).path, "s");
  assert.equal(pickThumbnail([], 64), null);
  assert.equal(pickThumbnail(undefined, 64), null);
});

test("clock formatting: today shows only the time, later days add the weekday", () => {
  const now = new Date(2026, 0, 7, 12, 0, 0).getTime();            // a Wednesday, local time
  const at = (d, h, m) => new Date(2026, 0, d, h, m, 0).getTime() / 1000;
  assert.match(formatClock(at(7, 14, 5), now), /^\d{1,2}:05|^14:05|^2:05/);
  assert.ok(!/[A-Za-z]/.test(formatClock(at(7, 14, 5), now).replace(/\s?[AP]M$/i, "")));
  assert.match(formatClock(at(9, 2, 10), now), /^[A-Za-z]+\.? /);
  assert.equal(formatClock(null, now), "");
  assert.notEqual(formatClock(at(7, 14, 5), now), formatClock(at(9, 14, 5), now));
});
