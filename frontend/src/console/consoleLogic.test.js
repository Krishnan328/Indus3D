/**
 * consoleLogic.test.js — unit tests for the pure console filter + autocomplete helpers.
 *
 * Uses Node's built-in test runner (node:test + node:assert/strict).
 * Run via:  cd frontend && npm test
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  isValidRegex,
  buildFilterPredicate,
  applyFilter,
  buildCompletionList,
  getCompletions,
  BUILTIN_PRESETS,
  STATIC_GCODES,
  loadFilterMode,
  saveFilterMode,
  loadUserPresets,
  saveUserPresets,
} from "./consoleLogic.js";

// ── Stub localStorage for the pure-logic tests ────────────────────────────────
let _store = {};
globalThis.localStorage = {
  getItem:    (k)    => _store[k] ?? null,
  setItem:    (k, v) => { _store[k] = v; },
  removeItem: (k)    => { delete _store[k]; },
  clear:      ()     => { _store = {}; },
};

// helper: reset localStorage before each sub-block
function resetStorage() { _store = {}; }

// ── isValidRegex ──────────────────────────────────────────────────────────────
describe("isValidRegex", () => {
  test("accepts valid patterns", () => {
    assert.equal(isValidRegex(""),        true);
    assert.equal(isValidRegex("hello"),   true);
    assert.equal(isValidRegex("^ok T"),   true);
    assert.equal(isValidRegex("\\d+"),    true);
    assert.equal(isValidRegex("[A-Z]+"),  true);
  });

  test("rejects invalid patterns", () => {
    assert.equal(isValidRegex("[invalid"), false);
    assert.equal(isValidRegex("(unclosed"), false);
    assert.equal(isValidRegex("*bad"),     false);
  });
});

// ── buildFilterPredicate ──────────────────────────────────────────────────────
describe("buildFilterPredicate", () => {
  test("returns null for empty pattern", () => {
    assert.equal(buildFilterPredicate("", "contains",    true),  null);
    assert.equal(buildFilterPredicate("", "starts-with", false), null);
    assert.equal(buildFilterPredicate("", "regex",       false), null);
  });

  test("returns null for invalid regex pattern", () => {
    assert.equal(buildFilterPredicate("[bad", "regex", false), null);
  });

  describe("contains mode", () => {
    test("case-insensitive matches", () => {
      const pred = buildFilterPredicate("HELLO", "contains", false);
      assert.ok(pred("say hello world"));
      assert.ok(pred("HELLO WORLD"));
      assert.ok(!pred("goodbye"));
    });

    test("case-sensitive matches", () => {
      const pred = buildFilterPredicate("HELLO", "contains", true);
      assert.ok(pred("say HELLO"));
      assert.ok(!pred("say hello"));
    });
  });

  describe("starts-with mode", () => {
    test("case-insensitive", () => {
      const pred = buildFilterPredicate("!!", "starts-with", false);
      assert.ok(pred("!! Error: heater fault"));
      assert.ok(!pred("ok !! not at start"));
    });

    test("case-sensitive", () => {
      const pred = buildFilterPredicate(">>>", "starts-with", true);
      assert.ok(pred(">>> G28"));
      assert.ok(!pred("ok >>> G28"));
    });
  });

  describe("regex mode", () => {
    test("matches regex patterns", () => {
      const pred = buildFilterPredicate("^ok T\\d*:", "regex", false);
      assert.ok(pred("ok T:210.0"));
      assert.ok(pred("ok T0:210.0"));
      assert.ok(!pred("ok B:60.0"));
    });

    test("case-insensitive flag works", () => {
      const pred = buildFilterPredicate("error", "regex", false);
      assert.ok(pred("ERROR: something"));
      assert.ok(pred("Error: something"));
    });

    test("case-sensitive flag works", () => {
      const pred = buildFilterPredicate("ERROR", "regex", true);
      assert.ok(pred("ERROR: something"));
      assert.ok(!pred("error: something"));
    });
  });
});

// ── applyFilter ───────────────────────────────────────────────────────────────
describe("applyFilter", () => {
  const lines = [
    { text: "!! extruder fault" },
    { text: "ok T:210.0 /210.0 B:60.0" },
    { text: ">>> G28" },
    { text: "[INDUS] Starting QC" },
    { text: "echo:busy processing" },
  ];

  test("returns same array reference when predicate is null", () => {
    const result = applyFilter(lines, null);
    assert.strictEqual(result, lines);
  });

  test("filters to only error lines", () => {
    const pred = buildFilterPredicate("!!", "starts-with", true);
    const result = applyFilter(lines, pred);
    assert.equal(result.length, 1);
    assert.equal(result[0].text, "!! extruder fault");
  });

  test("filters user commands", () => {
    const pred = buildFilterPredicate(">>> ", "starts-with", true);
    const result = applyFilter(lines, pred);
    assert.equal(result.length, 1);
    assert.equal(result[0].text, ">>> G28");
  });

  test("handles lines with undefined text gracefully", () => {
    const weirdLines = [{ text: undefined }, { text: "hello" }];
    const pred = buildFilterPredicate("hello", "contains", false);
    const result = applyFilter(weirdLines, pred);
    assert.equal(result.length, 1);
  });

  test("count equals total when predicate matches all", () => {
    const pred = buildFilterPredicate("", "contains", false); // empty → null
    const result = applyFilter(lines, pred);
    assert.equal(result.length, lines.length); // null predicate → pass-through
  });
});

// ── buildCompletionList ───────────────────────────────────────────────────────
describe("buildCompletionList", () => {
  test("includes static gcodes", () => {
    const list = buildCompletionList([], []);
    for (const g of ["G28", "M104", "M600"]) {
      assert.ok(list.includes(g), `expected ${g} in list`);
    }
  });

  test("merges quick commands", () => {
    const list = buildCompletionList(["FIRMWARE_RESTART", "RESTART"], []);
    assert.ok(list.includes("FIRMWARE_RESTART"));
    assert.ok(list.includes("RESTART"));
  });

  test("merges macros, skipping private ones (_prefixed)", () => {
    const list = buildCompletionList([], ["MY_MACRO", "_PRIVATE", "CLEAN_NOZZLE"]);
    assert.ok(list.includes("MY_MACRO"));
    assert.ok(list.includes("CLEAN_NOZZLE"));
    assert.ok(!list.includes("_PRIVATE"));
  });

  test("deduplicates", () => {
    const list = buildCompletionList(["G28", "G28"], ["G28"]);
    const count = list.filter((x) => x === "G28").length;
    assert.equal(count, 1);
  });

  test("result is sorted alphabetically", () => {
    const list = buildCompletionList(["ZZZCMD", "AAACMD"], []);
    const idx_aaa = list.indexOf("AAACMD");
    const idx_zzz = list.indexOf("ZZZCMD");
    assert.ok(idx_aaa < idx_zzz);
  });
});

// ── getCompletions ────────────────────────────────────────────────────────────
describe("getCompletions", () => {
  const candidates = ["G0", "G1", "G28", "G29", "M104", "M109", "M600", "RESTART", "RESUME", "RESTORE_STATE"];

  test("returns empty for empty input", () => {
    assert.deepEqual(getCompletions("", candidates), []);
  });

  test("matches prefix case-insensitively", () => {
    const r = getCompletions("g2", candidates);
    assert.ok(r.includes("G28"));
    assert.ok(r.includes("G29"));
    assert.ok(!r.includes("G0"));
  });

  test("exact match returns that entry", () => {
    const r = getCompletions("G28", candidates);
    assert.ok(r.includes("G28"));
    assert.equal(r.length, 1);
  });

  test("returns at most 10 results", () => {
    // Build candidates with 15 entries all starting with "M"
    const many = Array.from({ length: 15 }, (_, i) => `M${i + 100}`);
    const r = getCompletions("M", many);
    assert.ok(r.length <= 10);
  });

  test("no match returns empty array", () => {
    assert.deepEqual(getCompletions("ZZZNOMATCH", candidates), []);
  });
});

// ── BUILTIN_PRESETS ───────────────────────────────────────────────────────────
describe("BUILTIN_PRESETS", () => {
  test("contains exactly 5 built-in presets", () => {
    assert.equal(BUILTIN_PRESETS.length, 5);
  });

  test("all presets have required fields", () => {
    for (const p of BUILTIN_PRESETS) {
      assert.ok(p.name,    `preset missing name`);
      assert.ok(p.pattern, `preset '${p.name}' missing pattern`);
      assert.ok(["contains", "starts-with", "regex"].includes(p.mode), `preset '${p.name}' has bad mode`);
      assert.equal(typeof p.caseSensitive, "boolean");
      assert.equal(p.builtin, true);
    }
  });

  test("'Errors only' preset matches error lines", () => {
    const p = BUILTIN_PRESETS.find((x) => x.name === "Errors only");
    const pred = buildFilterPredicate(p.pattern, p.mode, p.caseSensitive);
    assert.ok(pred("!! extruder fault"));
    assert.ok(!pred("ok T:200"));
  });

  test("'Indus3D messages' preset matches INDUS lines", () => {
    const p = BUILTIN_PRESETS.find((x) => x.name === "Indus3D messages");
    const pred = buildFilterPredicate(p.pattern, p.mode, p.caseSensitive);
    assert.ok(pred("[INDUS] QC pass"));
    assert.ok(!pred("ok T:200"));
  });

  test("'User commands' preset matches >>> lines", () => {
    const p = BUILTIN_PRESETS.find((x) => x.name === "User commands");
    const pred = buildFilterPredicate(p.pattern, p.mode, p.caseSensitive);
    assert.ok(pred(">>> G28"));
    assert.ok(!pred("ok G28 done"));
  });

  test("'No SD status' preset filters SD lines", () => {
    const p = BUILTIN_PRESETS.find((x) => x.name === "No SD status");
    const pred = buildFilterPredicate(p.pattern, p.mode, p.caseSensitive);
    assert.ok(pred("echo:SD printing byte 0/0"));
    assert.ok(!pred("ok echo:ok"));
  });
});

// ── STATIC_GCODES ─────────────────────────────────────────────────────────────
describe("STATIC_GCODES", () => {
  test("contains all spec-required codes", () => {
    const required = ["G0","G1","G28","G29","G34","G80","G92","M84","M104","M109","M140","M190","M220","M221","M400","M600","M603","M701","M702"];
    for (const code of required) {
      assert.ok(STATIC_GCODES.includes(code), `missing ${code}`);
    }
  });
});

// ── localStorage helpers ──────────────────────────────────────────────────────
describe("loadFilterMode / saveFilterMode", () => {
  test("defaults to 'contains' when nothing stored", () => {
    resetStorage();
    assert.equal(loadFilterMode(), "contains");
  });

  test("round-trips all valid modes", () => {
    for (const mode of ["contains", "starts-with", "regex"]) {
      resetStorage();
      saveFilterMode(mode);
      assert.equal(loadFilterMode(), mode);
    }
  });

  test("ignores unknown stored values and returns default", () => {
    _store["indus3d_console_filter_mode"] = "invalid";
    assert.equal(loadFilterMode(), "contains");
  });
});

describe("loadUserPresets / saveUserPresets", () => {
  test("returns empty array when nothing stored", () => {
    resetStorage();
    assert.deepEqual(loadUserPresets(), []);
  });

  test("round-trips user presets", () => {
    resetStorage();
    const presets = [
      { name: "My filter", pattern: "TEMP", mode: "contains", caseSensitive: false },
    ];
    saveUserPresets(presets);
    const loaded = loadUserPresets();
    assert.equal(loaded.length, 1);
    assert.equal(loaded[0].name, "My filter");
  });

  test("caps at 5 presets on save", () => {
    resetStorage();
    const presets = Array.from({ length: 8 }, (_, i) => ({
      name: `P${i}`, pattern: `p${i}`, mode: "contains", caseSensitive: false,
    }));
    saveUserPresets(presets);
    assert.ok(loadUserPresets().length <= 5);
  });

  test("handles corrupt JSON gracefully", () => {
    _store["indus3d_console_presets"] = "not-json{{{";
    assert.deepEqual(loadUserPresets(), []);
  });

  test("handles non-array JSON gracefully", () => {
    _store["indus3d_console_presets"] = JSON.stringify({ not: "array" });
    assert.deepEqual(loadUserPresets(), []);
  });
});
