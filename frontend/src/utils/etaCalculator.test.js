import test, { describe } from "node:test";
import assert from "node:assert/strict";
import {
  calculateProgressAndEta,
  formatEtaDisplay,
  ETA_METHODS,
} from "./etaCalculator.js";

describe("calculateProgressAndEta", () => {
  test("never compares consumed millimetres with a spool weight in grams", () => {
    const result = calculateProgressAndEta(ETA_METHODS.FILAMENT,
      { filament_used: 10, progress: 0.25, print_duration: 100 },
      { filament_weight_total: 20 });
    assert.equal(result.methodUsed, "filament (fallback to file)");
    assert.equal(result.remainingSeconds, 300);
  });
  test("calculates file position ETA accurately", () => {
    // 50% done in 1000s -> 1000s remaining
    const res = calculateProgressAndEta(ETA_METHODS.FILE, {
      progress: 0.5,
      print_duration: 1000,
    });
    assert.equal(res.progressPercent, 50.0);
    assert.equal(res.remainingSeconds, 1000);
    assert.equal(res.methodUsed, ETA_METHODS.FILE);
  });

  test("calculates filament-based ETA when available", () => {
    // 20g out of 100g used in 500s -> 2000s remaining
    const res = calculateProgressAndEta(
      ETA_METHODS.FILAMENT,
      { filament_used: 20, print_duration: 500, progress: 0.25 },
      { filament_total: 100 }
    );
    assert.equal(res.progressPercent, 20.0);
    assert.equal(res.remainingSeconds, 2000);
    assert.equal(res.methodUsed, ETA_METHODS.FILAMENT);
  });

  test("calculates slicer estimate ETA", () => {
    // estimated 3600s, 1000s elapsed -> 2600s remaining
    const res = calculateProgressAndEta(
      ETA_METHODS.SLICER,
      { print_duration: 1000, progress: 0.3 },
      { estimated_time: 3600 }
    );
    assert.equal(res.remainingSeconds, 2600);
    assert.equal(res.methodUsed, ETA_METHODS.SLICER);
  });

  test("calculates M73 G-code ETA", () => {
    const res = calculateProgressAndEta(ETA_METHODS.M73, {
      progress: 0.1,
      print_duration: 60,
      m73_progress: 15,
      m73_remaining_s: 1800,
    });
    assert.equal(res.progressPercent, 15.0);
    assert.equal(res.remainingSeconds, 1800);
    assert.equal(res.methodUsed, ETA_METHODS.M73);
  });

  test("weighted early print prefers slicer metadata", () => {
    // < 15% progress (5% done), file estimate would be distorted
    const res = calculateProgressAndEta(
      ETA_METHODS.WEIGHTED,
      { progress: 0.05, print_duration: 120 },
      { estimated_time: 2400 }
    );
    assert.equal(res.remainingSeconds, 2400 - 120);
    assert.equal(res.methodUsed, "slicer (early)");
  });

  test("weighted mid-print blends estimators", () => {
    const res = calculateProgressAndEta(
      ETA_METHODS.WEIGHTED,
      { progress: 0.5, print_duration: 1000, filament_used: 50 },
      { estimated_time: 2000, filament_total: 100 }
    );
    // All 3 methods agree on 1000s remaining
    assert.equal(res.remainingSeconds, 1000);
    assert.equal(res.methodUsed, ETA_METHODS.WEIGHTED);
  });

  test("falls back cleanly when data is missing", () => {
    const res = calculateProgressAndEta(ETA_METHODS.FILAMENT, { progress: 0.5, print_duration: 500 });
    assert.equal(res.progressPercent, 50.0);
    assert.equal(res.remainingSeconds, 500);
    assert.match(res.methodUsed, /fallback/);
  });
});

describe("formatEtaDisplay", () => {
  test("formats empty or zero seconds", () => {
    assert.equal(formatEtaDisplay(0), "--");
    assert.equal(formatEtaDisplay(null), "--");
  });

  test("formats duration and clock time", () => {
    const fakeFormat = () => "14:30";
    const str = formatEtaDisplay(3600, fakeFormat);
    assert.equal(str, "~1h 0m (ETA 14:30)");
  });
});
