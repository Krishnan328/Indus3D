import React, { useEffect, useState } from "react";
import { Disc3, RefreshCw, QrCode, AlertTriangle, Layers } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

// ── Spool picker ─────────────────────────────────────────────────────────────
// Supports active spool selection, multi-extruder / toolchanger assignment (T0/T1),
// quick QR / spool ID code entry, and live volumetric flow tracking.
export function SpoolPicker() {
  const spoolmanConnected = useStore((s) => s.spoolmanConnected);
  const spoolmanError     = useStore((s) => s.spoolmanError);
  const spools            = useStore((s) => s.spools);
  const activeSpoolId     = useStore((s) => s.activeSpoolId);
  const fetchSpoolStatus  = useStore((s) => s.fetchSpoolStatus);
  const fetchSpools       = useStore((s) => s.fetchSpools);
  const setActiveSpool    = useStore((s) => s.setActiveSpool);
  const extrusion         = useStore((s) => s.extrusion);
  const extruders         = useStore((s) => s.printerStatus?.extruders || ["extruder"]);

  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const [loading, setLoading] = useState(false);
  const [activeTool, setActiveTool] = useState(0);
  const [showQrInput, setShowQrInput] = useState(false);
  const [qrCode, setQrCode] = useState("");

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

  const handleQrSubmit = (e) => {
    e.preventDefault();
    const query = qrCode.trim().toLowerCase();
    if (!query) return;

    const match = spools.find((s) =>
      String(s.id) === query ||
      (s.lot_number && s.lot_number.toLowerCase().includes(query)) ||
      (s.filament?.name && s.filament.name.toLowerCase().includes(query))
    );

    if (match) {
      setActiveSpool(match.id, activeTool);
      setShowQrInput(false);
      setQrCode("");
    } else {
      alert(`Spool matching code "${qrCode}" not found.`);
    }
  };

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
        <div className="flex items-center gap-1.5">
          <span className={t.label}>Filament Spool</span>
          {/* Toolchanger / multi-extruder tabs if multiple extruders exist */}
          {extruders.length > 1 && (
            <div className="flex gap-1 ml-2">
              {extruders.map((ex, idx) => (
                <button
                  key={ex}
                  onClick={() => setActiveTool(idx)}
                  className={`px-1.5 py-0.2 rounded text-[8px] font-bold uppercase ${
                    activeTool === idx ? "bg-blue-600 text-white" : "bg-white/10 opacity-60"
                  }`}
                >
                  T{idx}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowQrInput(!showQrInput)}
            title="Scan QR or Enter Spool Code"
            className="opacity-50 hover:opacity-100 transition-opacity p-0.5"
          >
            <QrCode size={12} className={showQrInput ? "text-blue-400" : ""} />
          </button>
          <button onClick={refresh} disabled={loading} className="opacity-50 hover:opacity-100 p-0.5">
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {showQrInput ? (
        <form onSubmit={handleQrSubmit} className="flex gap-1.5 animate-fade-in">
          <input
            type="text"
            value={qrCode}
            onChange={(e) => setQrCode(e.target.value)}
            placeholder="Spool ID or QR payload..."
            className={`flex-1 text-xs px-2 py-1 font-mono outline-none rounded ${
              brutalist ? "border-2 border-[#111] bg-white text-[#111]" : "bg-black/40 border border-white/20 text-white"
            }`}
            autoFocus
          />
          <button
            type="submit"
            className="px-2 py-1 text-[10px] font-bold rounded bg-blue-600 text-white"
          >
            Apply
          </button>
        </form>
      ) : (
        <div className="flex items-center gap-2">
          {active && (
            <span
              className={`w-3 h-3 shrink-0 ${brutalist ? "border-2 border-[#111]" : "rounded-full border border-black/20"}`}
              style={{ backgroundColor: active.filament?.color_hex ? `#${active.filament.color_hex}` : "#999" }}
            />
          )}
          <select
            value={activeSpoolId ?? ""}
            onChange={(e) => setActiveSpool(e.target.value ? Number(e.target.value) : null, activeTool)}
            className={`flex-1 text-xs px-2 py-1 outline-none ${
              brutalist ? "border-2 border-[#111] rounded-none font-mono bg-white" : soft ? t.softInput : "bg-gray-800 border border-gray-700 rounded"
            }`}
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
      )}

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
