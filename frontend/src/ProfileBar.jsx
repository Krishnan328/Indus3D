/**
 * ProfileBar.jsx
 * ---------------
 * Shows the loaded printer name, profile source (Moonraker / local file / JSON fallback),
 * and a Reload button that calls POST /api/profile/reload without restarting anything.
 *
 * Drop this component just below <TopHeader /> in App.jsx:
 *
 *   <TopHeader ... />
 *   <ProfileBar isDarkMode={isDarkMode} />
 *   <AlertBar isDarkMode={isDarkMode} />
 *
 * Add to App.jsx's useEffect block:
 *   const fetchProfile   = useStore((s) => s.fetchProfile);
 *   useEffect(() => { fetchProfile(); }, [fetchProfile]);
 */

import React, { useState } from "react";
import { RefreshCw, Cpu } from "lucide-react";
import { useStore } from "./store";

export function ProfileBar({ isDarkMode }) {
  const profile       = useStore((s) => s.profile);
  const profileSource = useStore((s) => s.profileSource);
  const reloadProfile = useStore((s) => s.reloadProfile);
  const simMode       = useStore((s) => s.simMode);

  const [reloading, setReloading] = useState(false);
  const [feedback,  setFeedback]  = useState("");

  const handleReload = async () => {
    setReloading(true);
    setFeedback("");
    const result = await reloadProfile();
    setReloading(false);
    setFeedback(result.ok ? `✅ Reloaded from ${result.source}` : `❌ ${result.message}`);
    setTimeout(() => setFeedback(""), 4000);
  };

  if (!profile) return null;

  const bar = isDarkMode
    ? "bg-gray-900 border-gray-800 text-gray-400"
    : "bg-gray-50 border-gray-200 text-gray-500";

  // Source badge colour
  const srcColour =
    profileSource.includes("Moonraker") ? "text-green-400" :
    profileSource.includes("local")     ? "text-yellow-400" :
                                          "text-red-400";

  return (
    <div className={`flex items-center justify-between px-4 py-1.5 mb-2 rounded-xl border text-xs font-mono ${bar}`}>
      <div className="flex items-center gap-3">
        <Cpu size={13} className="opacity-60" />
        <span className="font-bold tracking-wide text-gray-300">
          {profile.printer_name ?? "Unknown Printer"}
        </span>
        <span className="opacity-40">|</span>
        <span className="opacity-60">
          {profile.bed?.size_x_mm ?? 0} × {profile.bed?.size_y_mm ?? 0} × {profile.bed?.size_z_mm ?? 0} mm
        </span>
        <span className="opacity-40">|</span>
        <span className="opacity-60">
          ⌀{profile.hotend?.nozzle_diameter_mm ?? "?"} mm nozzle
        </span>
        {simMode && (
          <span className="px-2 py-0.5 bg-blue-700 text-white rounded-full text-[9px] font-bold uppercase tracking-widest">
            SIM
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        {feedback && <span className="text-[10px]">{feedback}</span>}
        <span className={`text-[10px] ${srcColour}`}>
          {profileSource || "unknown source"}
        </span>
        <button
          onClick={handleReload}
          disabled={reloading}
          title="Re-parse printer.cfg from Moonraker"
          className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors text-[10px] font-bold uppercase tracking-widest
                      ${isDarkMode
                        ? "border-gray-700 hover:border-blue-500 hover:text-blue-400"
                        : "border-gray-300 hover:border-blue-500 hover:text-blue-600"}`}>
          <RefreshCw size={11} className={reloading ? "animate-spin" : ""} />
          {reloading ? "Reloading…" : "Reload cfg"}
        </button>
      </div>
    </div>
  );
}
