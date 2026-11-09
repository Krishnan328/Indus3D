/**
 * etaCalculator.js
 * ----------------
 * Pure utility functions for calculating print progress and ETA
 * using different estimation strategies (file, filament, slicer, m73, weighted).
 */

export const ETA_METHODS = {
  WEIGHTED: "weighted",
  FILE: "file",
  FILAMENT: "filament",
  SLICER: "slicer",
  M73: "m73",
};

/**
 * Calculate progress percent (0-100) and remaining seconds.
 *
 * @param {string} method - "file" | "filament" | "slicer" | "m73" | "weighted"
 * @param {object} telemetry - live printer telemetry
 * @param {object} metadata - slicer metadata for current file
 * @returns {{ progressPercent: number, remainingSeconds: number, methodUsed: string }}
 */
export function calculateProgressAndEta(method = ETA_METHODS.WEIGHTED, telemetry = {}, metadata = {}) {
  const duration = Math.max(0, Number(telemetry.print_duration || 0));
  const fileProg = Math.max(0, Math.min(1, Number(telemetry.progress || 0)));

  // 1. File position estimation
  const fileRemaining = fileProg > 0.005 ? Math.max(0, Math.round((duration / fileProg) * (1 - fileProg))) : 0;
  const filePercent = Math.round(fileProg * 1000) / 10;

  // 2. Filament estimation
  const filUsed = Number(telemetry.filament_used || 0);
  // Klipper reports consumed filament length in mm, not grams.
  const filTotal = Number(metadata?.filament_total || 0);
  let filProg = 0;
  let filRemaining = null;
  if (filTotal > 0 && filUsed > 0) {
    filProg = Math.max(0, Math.min(1, filUsed / filTotal));
    if (filProg > 0.005) {
      filRemaining = Math.max(0, Math.round((duration / filProg) * (1 - filProg)));
    }
  }

  // 3. Slicer metadata estimation
  const slicerEst = Number(metadata?.estimated_time || 0);
  let slicerRemaining = null;
  let slicerProg = 0;
  if (slicerEst > 0) {
    slicerRemaining = Math.max(0, Math.round(slicerEst - duration));
    slicerProg = Math.max(0, Math.min(1, duration / slicerEst));
  }

  // 4. M73 G-code estimation
  const m73ProgRaw = telemetry.m73_progress ?? telemetry.m73?.progress;
  const m73RemRaw = telemetry.m73_remaining_s ?? (telemetry.m73?.remaining_time !== undefined ? telemetry.m73.remaining_time * 60 : null);
  let m73Prog = null;
  let m73Remaining = null;
  if (m73ProgRaw !== undefined && m73ProgRaw !== null && !isNaN(Number(m73ProgRaw))) {
    m73Prog = Math.max(0, Math.min(1, Number(m73ProgRaw) / 100));
  }
  if (m73RemRaw !== undefined && m73RemRaw !== null && !isNaN(Number(m73RemRaw))) {
    m73Remaining = Math.max(0, Math.round(Number(m73RemRaw)));
  }

  // Choose calculation
  switch (method) {
    case ETA_METHODS.M73:
      if (m73Remaining !== null) {
        return {
          progressPercent: m73Prog !== null ? Math.round(m73Prog * 1000) / 10 : filePercent,
          remainingSeconds: m73Remaining,
          methodUsed: ETA_METHODS.M73,
        };
      }
      break;

    case ETA_METHODS.FILAMENT:
      if (filRemaining !== null) {
        return {
          progressPercent: Math.round(filProg * 1000) / 10,
          remainingSeconds: filRemaining,
          methodUsed: ETA_METHODS.FILAMENT,
        };
      }
      break;

    case ETA_METHODS.SLICER:
      if (slicerRemaining !== null) {
        return {
          progressPercent: Math.round(slicerProg * 1000) / 10,
          remainingSeconds: slicerRemaining,
          methodUsed: ETA_METHODS.SLICER,
        };
      }
      break;

    case ETA_METHODS.FILE:
      return {
        progressPercent: filePercent,
        remainingSeconds: fileRemaining,
        methodUsed: ETA_METHODS.FILE,
      };

    case ETA_METHODS.WEIGHTED:
    default: {
      // If M73 is explicitly active from slicer, give it highest weight
      if (m73Remaining !== null && m73Prog !== null) {
        return {
          progressPercent: Math.round(m73Prog * 1000) / 10,
          remainingSeconds: m73Remaining,
          methodUsed: ETA_METHODS.M73,
        };
      }

      // Early phase (< 15% file progress): slicer metadata estimate is much more reliable
      // than extrapolation from initial heating and prime moves
      if (fileProg < 0.15 && slicerRemaining !== null) {
        return {
          progressPercent: filePercent,
          remainingSeconds: slicerRemaining,
          methodUsed: "slicer (early)",
        };
      }

      // Mid/late print: blend available estimators
      const estimates = [];
      if (fileRemaining > 0) estimates.push({ val: fileRemaining, weight: 0.5 });
      if (filRemaining !== null && filRemaining > 0) estimates.push({ val: filRemaining, weight: 0.3 });
      if (slicerRemaining !== null && slicerRemaining > 0) estimates.push({ val: slicerRemaining, weight: 0.2 });

      if (estimates.length > 0) {
        const totalWeight = estimates.reduce((acc, e) => acc + e.weight, 0);
        const weightedSum = estimates.reduce((acc, e) => acc + e.val * e.weight, 0);
        const blendedSeconds = Math.round(weightedSum / totalWeight);
        return {
          progressPercent: filePercent,
          remainingSeconds: blendedSeconds,
          methodUsed: ETA_METHODS.WEIGHTED,
        };
      }

      return {
        progressPercent: filePercent,
        remainingSeconds: fileRemaining,
        methodUsed: ETA_METHODS.FILE,
      };
    }
  }

  // Fallback if specific method requested has no data
  return {
    progressPercent: filePercent,
    remainingSeconds: fileRemaining,
    methodUsed: `${method} (fallback to file)`,
  };
}

/**
 * Format remaining seconds into human-readable string and ETA clock time.
 * e.g., "~45m (ETA 16:42)"
 */
export function formatEtaDisplay(remainingSeconds, formatTime) {
  if (!remainingSeconds || remainingSeconds <= 0) return "--";

  const totalMinutes = Math.round(remainingSeconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  const durationStr = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;

  const etaDate = new Date(Date.now() + remainingSeconds * 1000);
  const clockStr = formatTime ? formatTime(etaDate) : etaDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return `~${durationStr} (ETA ${clockStr})`;
}
