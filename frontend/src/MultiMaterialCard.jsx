import React from "react";
import { Layers } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

const text = (value) => typeof value === "string" || typeof value === "number" ? String(value) : "Unknown";

export function MultiMaterialCard() {
  const t = useThemeTokens();
  const mmu = useStore((state) => state.telemetry?.mmu);
  const afc = useStore((state) => state.telemetry?.afc);
  const unit = mmu || afc;
  if (!unit || typeof unit !== "object") return null;
  const gates = Array.isArray(unit.gates) ? unit.gates.slice(0, 32) : [];
  return (
    <section className={`p-4 mb-3 shrink-0 ${t.panel}`}>
      <h3 className="flex items-center gap-2 font-semibold text-xs uppercase">
        <Layers size={16} /> Multi-material — {mmu ? "Happy Hare" : "AFC"}
      </h3>
      <p className="text-xs my-2">
        Active gate: {text(unit.gate ?? unit.tool)} · Action: {text(unit.action)}
      </p>
      {gates.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {gates.map((gate, index) => (
            <span key={index}>Gate {index}: {text(gate?.status ?? gate)}</span>
          ))}
        </div>
      )}
      <p className="text-xs opacity-60 mt-2">
        Read-only hardware status. Loading/ejecting requires verified firmware macros;
        untested generic commands are not sent from this panel.
      </p>
    </section>
  );
}
