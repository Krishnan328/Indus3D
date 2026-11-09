import test, { describe } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_MACRO_CONFIG,
  filterMacrosByState,
  groupMacros,
  loadMacroConfigs,
  saveMacroConfigs,
  MACRO_CONFIGS_STORAGE_KEY,
} from "./macroSlice.js";

describe("filterMacrosByState", () => {
  const macros = ["G28", "PAUSE", "RESUME", "LOAD_FILAMENT", "CLEAN_NOZZLE"];

  test("returns all when showWhen is always or default", () => {
    const res = filterMacrosByState(macros, {}, "printing");
    assert.deepEqual(res, macros);
  });

  test("filters by idle state", () => {
    const configs = {
      CLEAN_NOZZLE: { showWhen: "idle" },
      RESUME: { showWhen: "paused" },
    };
    const idleRes = filterMacrosByState(macros, configs, "idle");
    assert.ok(idleRes.includes("CLEAN_NOZZLE"));
    assert.ok(!idleRes.includes("RESUME"));

    const printingRes = filterMacrosByState(macros, configs, "printing");
    assert.ok(!printingRes.includes("CLEAN_NOZZLE"));
    assert.ok(!printingRes.includes("RESUME"));
  });

  test("filters by paused and printing state", () => {
    const configs = {
      RESUME: { showWhen: "paused" },
      PAUSE: { showWhen: "printing" },
    };
    const pausedRes = filterMacrosByState(macros, configs, "paused");
    assert.ok(pausedRes.includes("RESUME"));
    assert.ok(!pausedRes.includes("PAUSE"));

    const printingRes = filterMacrosByState(macros, configs, "printing");
    assert.ok(!printingRes.includes("RESUME"));
    assert.ok(printingRes.includes("PAUSE"));
  });

  test("handles empty or invalid inputs safely", () => {
    assert.deepEqual(filterMacrosByState(null), []);
    assert.deepEqual(filterMacrosByState([]), []);
  });
});

describe("groupMacros", () => {
  const macros = ["G28", "LOAD_FILAMENT", "UNLOAD_FILAMENT", "LED_ON"];

  test("groups macros by configured group", () => {
    const configs = {
      LOAD_FILAMENT: { group: "Filament" },
      UNLOAD_FILAMENT: { group: "Filament" },
      LED_ON: { group: "Lighting" },
    };
    const groups = groupMacros(macros, configs);
    assert.deepEqual(groups.General, ["G28"]);
    assert.deepEqual(groups.Filament, ["LOAD_FILAMENT", "UNLOAD_FILAMENT"]);
    assert.deepEqual(groups.Lighting, ["LED_ON"]);
  });

  test("defaults to General group", () => {
    const groups = groupMacros(macros, {});
    assert.deepEqual(groups.General, macros);
  });

  test("handles empty or invalid inputs", () => {
    assert.deepEqual(groupMacros(null), {});
    assert.deepEqual(groupMacros([]), {});
  });
});

describe("loadMacroConfigs & saveMacroConfigs", () => {
  test("storage round-trip", () => {
    const mem = {};
    const storage = {
      getItem: (k) => mem[k] ?? null,
      setItem: (k, v) => { mem[k] = String(v); },
    };

    assert.deepEqual(loadMacroConfigs(storage), {});

    const sample = { G28: { group: "Homing", color: "blue", showWhen: "idle" } };
    saveMacroConfigs(sample, storage);

    const loaded = loadMacroConfigs(storage);
    assert.deepEqual(loaded, sample);
  });
});
