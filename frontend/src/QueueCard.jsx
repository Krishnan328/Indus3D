import React from "react";
import { ListOrdered } from "lucide-react";
import { useThemeTokens } from "./theme";
import { QueuePanel } from "./files/QueuePanel";

// Dashboard card for the print queue (status, totals, ETA, reorder, start). The panel polls the queue only
// while this card is mounted.
export function QueueCard() {
  const t = useThemeTokens();
  return (
    <div className={`h-full flex flex-col gap-2 p-3 overflow-hidden ${t.panel}`}>
      <div className="flex items-center gap-2 shrink-0">
        <ListOrdered size={15} />
        <h3 className={t.heading}>Print queue</h3>
      </div>
      <div className="flex-1 min-h-0 overflow-auto"><QueuePanel compact /></div>
    </div>
  );
}
