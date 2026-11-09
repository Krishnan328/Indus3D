import React from "react";
import { Disc, Layers, RefreshCw, ArrowDownToLine, ArrowUpFromLine, CheckCircle2 } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

export function MultiMaterialCard({ isDarkMode }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const mmu = useStore((s) => s.telemetry?.mmu);
  const afc = useStore((s) => s.telemetry?.afc);
  const sendCommand = useStore((s) => s.sendCommand || s.injectGcode);

  const activeUnit = mmu || afc;
  const isEnabled = activeUnit && activeUnit.enabled !== false;

  const activeGate = activeUnit?.gate ?? activeUnit?.tool ?? 0;
  const actionText = activeUnit?.action || "Standby";
  const numGates = activeUnit?.gates?.length || 4;
  const gates = activeUnit?.gates || Array.from({ length: numGates }, (_, i) => ({
    gate: i,
    status: i === activeGate ? "loaded" : "available",
    material: `Lane ${i}`,
    color: ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"][i % 6],
  }));

  const handleSelectGate = (gateIdx) => {
    if (mmu) {
      sendCommand(`MMU_SELECT GATE=${gateIdx}`);
    } else if (afc) {
      sendCommand(`AFC_LOAD LANE=${gateIdx}`);
    } else {
      sendCommand(`T${gateIdx}`);
    }
  };

  const handleEject = () => {
    if (mmu) {
      sendCommand("MMU_EJECT");
    } else if (afc) {
      sendCommand("AFC_EJECT");
    }
  };

  return (
    <div className={`h-full p-4 flex flex-col justify-between ${t.panel}`}>
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="flex items-center gap-2 text-purple-400">
          <Layers size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-xs">
            Multi-Material System
            {activeUnit && (
              <span className="ml-2 text-[9px] px-1.5 py-0.5 bg-purple-900/60 text-purple-200 rounded font-mono">
                {mmu ? "Happy Hare" : "AFC"}
              </span>
            )}
          </h3>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono opacity-60 uppercase">{actionText}</span>
          <button
            onClick={handleEject}
            className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
            title="Eject Filament"
          >
            <ArrowUpFromLine size={13} />
          </button>
        </div>
      </div>

      {/* Gates / Lanes Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-2">
        {gates.map((g, idx) => {
          const isActive = idx === activeGate;
          const isLoaded = g.status === "loaded" || isActive;
          return (
            <button
              key={idx}
              onClick={() => handleSelectGate(idx)}
              className={`p-2.5 rounded-lg flex flex-col items-center gap-1.5 border transition-all text-center
                ${isActive
                  ? "bg-purple-600/20 border-purple-500 text-white shadow-md shadow-purple-950/40"
                  : "bg-white/[0.02] hover:bg-white/[0.06] border-white/5 text-gray-300"}`}
            >
              <div className="relative">
                <Disc
                  size={20}
                  style={{ color: g.color || "#888" }}
                  className={isActive ? "animate-pulse" : "opacity-80"}
                />
                {isLoaded && (
                  <span className="absolute -bottom-1 -right-1 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-black" />
                )}
              </div>
              <span className="text-xs font-mono font-bold">Gate {idx}</span>
              <span className="text-[9px] opacity-60 font-sans truncate max-w-[60px]">
                {g.material || (isLoaded ? "Loaded" : "Empty")}
              </span>
            </button>
          );
        })}
      </div>

      {/* Bottom Status Row */}
      <div className="flex items-center justify-between pt-2 border-t border-white/5 text-[10px] font-mono opacity-70">
        <span>Active Lane: T{activeGate}</span>
        <span>Filament: {activeUnit?.filament || (activeUnit?.filament_pos ? `${activeUnit.filament_pos}mm` : "Engaged")}</span>
      </div>
    </div>
  );
}
