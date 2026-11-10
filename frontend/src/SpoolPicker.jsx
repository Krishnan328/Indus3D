import React, { useEffect, useState } from "react";
import { Disc3, RefreshCw } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

// ── Spool picker ─────────────────────────────────────────────────────────────
// Requires Moonraker's [spoolman] component configured against a running
// Spoolman instance (moonraker.conf) — see docs/DEVELOPMENT.md. If it isn't
// configured this renders a single quiet line instead of an error, since
// Spoolman is optional infrastructure, not a requirement.
//
// The one thing Mainsail/Fluidd's spool widgets don't do: Indus3D's own
// extrusion_model.py already computes filament_consumed_m every tick from
// real volumetric flow (not just commanded E position), so we show it next
// to Moonraker's own usage figure. When the quality controller has been
// correcting flow, these two numbers diverging is itself a signal.
export function SpoolPicker() {
  const spoolmanConnected = useStore((s) => s.spoolmanConnected);
  const spoolmanError     = useStore((s) => s.spoolmanError);
  const spools            = useStore((s) => s.spools);
  const activeSpoolId     = useStore((s) => s.activeSpoolId);
  const fetchSpoolStatus  = useStore((s) => s.fetchSpoolStatus);
  const fetchSpools       = useStore((s) => s.fetchSpools);
  const setActiveSpool    = useStore((s) => s.setActiveSpool);
  const extrusion         = useStore((s) => s.extrusion);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const [loading, setLoading] = useState(false);

  // Manual refresh (button click) shows the spinner. The mount fetch below
  // deliberately does NOT go through this — calling fetchSpoolStatus/
  // fetchSpools directly avoids setting local state synchronously inside
  // the effect's call stack.
  const refresh = async () => {
    setLoading(true);
    await Promise.all([fetchSpoolStatus(), fetchSpools()]);
    setLoading(false);
  };

  useEffect(() => {
    fetchSpoolStatus();
    fetchSpools();
  }, [fetchSpoolStatus, fetchSpools]);

  const active = spools.find((sp) => sp.id === activeSpoolId);

  if (!spoolmanConnected && !spools.length) {
    return (
      <div className="flex items-center gap-2 text-[10px] opacity-40 italic mt-2">
        <Disc3 size={12} />
        Spoolman not connected{spoolmanError ? ` (${spoolmanError})` : ""}
      </div>
    );
  }

  return (
    <div className={`mt-2 pt-2 flex flex-col gap-1.5 ${brutalist ? "border-t-2 border-[#111]" : soft ? `border-t ${t.border}` : "border-t border-gray-800/50"}`}>
      <div className="flex items-center justify-between">
        <span className={t.label}>Filament spool</span>
        <button onClick={refresh} disabled={loading} className="opacity-50 hover:opacity-100">
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        {active && (
          <span
            className={`w-3 h-3 shrink-0 ${brutalist ? "border-2 border-[#111]" : "rounded-full border border-black/20"}`}
            style={{ backgroundColor: active.filament?.color_hex ? `#${active.filament.color_hex}` : "#999" }}
          />
        )}
        <select
          value={activeSpoolId ?? ""}
          onChange={(e) => setActiveSpool(e.target.value ? Number(e.target.value) : null)}
          className={`flex-1 text-xs px-2 py-1 outline-none ${brutalist ? "border-2 border-[#111] rounded-none font-mono bg-white" : soft ? t.softInput : "bg-gray-800 border border-gray-700 rounded"}`}
        >
          <option value="">None selected</option>
          {spools.map((sp) => (
            <option key={sp.id} value={sp.id}>
              {sp.filament?.vendor?.name ?? "?"} {sp.filament?.name ?? sp.filament?.material ?? `Spool ${sp.id}`}
              {" — "}{Math.round(sp.remaining_weight ?? 0)}g left
            </option>
          ))}
        </select>
      </div>

      {active && (
        <div className="flex justify-between text-[10px] font-mono opacity-70">
          <span>Moonraker: {((active.used_weight ?? 0)).toFixed(0)}g used</span>
          <span title="Computed by Indus3D's own extrusion model, from real volumetric flow">
            Indus3D: {(extrusion.filament_consumed_m ?? 0).toFixed(2)}m
          </span>
        </div>
      )}
    </div>
  );
}
