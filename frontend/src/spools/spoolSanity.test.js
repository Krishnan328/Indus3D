import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { checkSpoolSanity, SANITY_ISSUES } from "./spoolSanity.js";

describe("checkSpoolSanity", () => {
  it("passes when no filament is needed by file", () => {
    const res = checkSpoolSanity(null, {});
    assert.equal(res.ok, true);
    assert.equal(res.issues.length, 0);
  });

  it("warns when file needs filament but no spool is selected", () => {
    const res = checkSpoolSanity(null, { filament_weight_total: 45.0 });
    assert.equal(res.ok, false);
    assert.equal(res.issues[0].type, SANITY_ISSUES.NO_SPOOL);
  });

  it("warns on material mismatch", () => {
    const spool = {
      id: 1,
      filament: { material: "PLA" },
      remaining_weight: 500,
    };
    const meta = {
      filament_type: "PETG",
      filament_weight_total: 50,
    };
    const res = checkSpoolSanity(spool, meta);
    assert.equal(res.ok, false);
    assert.equal(res.issues[0].type, SANITY_ISSUES.MATERIAL_MISMATCH);
  });

  it("allows compatible material variants (e.g. PLA vs PLA+)", () => {
    const spool = {
      id: 1,
      filament: { material: "PLA" },
      remaining_weight: 500,
    };
    const meta = {
      filament_type: "PLA+",
      filament_weight_total: 50,
    };
    const res = checkSpoolSanity(spool, meta);
    assert.equal(res.ok, true);
  });

  it("warns on insufficient spool weight", () => {
    const spool = {
      id: 1,
      filament: { material: "PLA" },
      remaining_weight: 40.0,
    };
    const meta = {
      filament_type: "PLA",
      filament_weight_total: 120.0,
    };
    const res = checkSpoolSanity(spool, meta);
    assert.equal(res.ok, false);
    assert.equal(res.issues[0].type, SANITY_ISSUES.INSUFFICIENT_WEIGHT);
  });

  it("passes cleanly when all checks succeed", () => {
    const spool = {
      id: 1,
      filament: { material: "PETG" },
      remaining_weight: 750.0,
    };
    const meta = {
      filament_type: "PETG",
      filament_weight_total: 150.0,
    };
    const res = checkSpoolSanity(spool, meta);
    assert.equal(res.ok, true);
    assert.equal(res.issues.length, 0);
  });
});
