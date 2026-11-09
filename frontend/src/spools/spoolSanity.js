/**
 * spoolSanity.js
 * --------------
 * Pre-print filament sanity checks comparing active spool attributes
 * against slicer file metadata.
 */

export const SANITY_ISSUES = {
  NO_SPOOL: "no_spool",
  MATERIAL_MISMATCH: "material_mismatch",
  INSUFFICIENT_WEIGHT: "insufficient_weight",
};

/**
 * Validate active spool against file metadata before starting a print.
 *
 * @param {object|null} activeSpool - Selected Spoolman spool object
 * @param {object|null} fileMeta - Slicer metadata of file to be printed
 * @returns {{ ok: boolean, issues: Array<{ type: string, severity: "warning"|"error", message: string }> }}
 */
export function checkSpoolSanity(activeSpool = null, fileMeta = {}) {
  const issues = [];
  const meta = fileMeta || {};

  const requiredGrams = Number(meta.filament_weight_total || 0);
  const requiredMm = Number(meta.filament_total || 0);
  const needsFilament = requiredGrams > 0 || requiredMm > 0;

  // 1. Check if spool is missing while file requires filament
  if (!activeSpool) {
    if (needsFilament) {
      issues.push({
        type: SANITY_ISSUES.NO_SPOOL,
        severity: "warning",
        message: "No active filament spool is selected for this print job.",
      });
    }
    return { ok: issues.length === 0, issues };
  }

  // 2. Check material compatibility
  const fileMaterial = (meta.filament_type || "").trim().toUpperCase();
  const spoolMaterial = (activeSpool.filament?.material || activeSpool.material || "").trim().toUpperCase();

  if (fileMaterial && spoolMaterial && fileMaterial !== spoolMaterial) {
    // Check if one is a subtype (e.g. PLA vs PLA+, PETG vs PETG-CF)
    const compatible = fileMaterial.startsWith(spoolMaterial) || spoolMaterial.startsWith(fileMaterial);
    if (!compatible) {
      issues.push({
        type: SANITY_ISSUES.MATERIAL_MISMATCH,
        severity: "warning",
        message: `Material mismatch: file is sliced for "${fileMaterial}", but active spool is "${spoolMaterial}".`,
      });
    }
  }

  // 3. Check remaining filament weight
  const remainingWeight = Number(activeSpool.remaining_weight ?? activeSpool.starting_weight_g ?? 0);
  if (requiredGrams > 0 && remainingWeight > 0 && remainingWeight < requiredGrams) {
    issues.push({
      type: SANITY_ISSUES.INSUFFICIENT_WEIGHT,
      severity: "warning",
      message: `Spool remaining weight (${Math.round(remainingWeight)}g) is less than required print weight (~${Math.round(requiredGrams)}g).`,
    });
  }

  return {
    ok: issues.length === 0,
    issues,
  };
}
