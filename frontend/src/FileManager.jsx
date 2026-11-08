import React, { useState } from "react";
import { Files, ListOrdered } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";
import { FilesBrowser } from "./files/FilesBrowser";
import { QueuePanel } from "./files/QueuePanel";

// Files page: the file browser (roots, sort, drag and drop, upload, preview, editor) and the print queue.
// Both tabs stay mounted-on-demand: the queue polls Moonraker only while its tab is open.
export function FileManager() {
  const t = useThemeTokens();
  const [tab, setTab] = useState("files");
  const queueCount = useStore((s) => s.queue.jobs.length);
  const tabBtn = (id, icon, label, badge) => (
    <button type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs ${tab === id ? "font-bold bg-white/15" : "opacity-70 hover:opacity-100"} ${t.chip}`}>
      {icon}{label}{badge > 0 && <span className="text-[10px] px-1.5 rounded-full bg-emerald-700 text-white">{badge}</span>}
    </button>
  );
  return (
    <div className="flex-1 min-h-0 flex flex-col gap-2">
      <div role="tablist" aria-label="Files and queue" className="flex items-center gap-1 shrink-0">
        {tabBtn("files", <Files size={13} />, "Files", 0)}
        {tabBtn("queue", <ListOrdered size={13} />, "Queue", queueCount)}
      </div>
      {tab === "files"
        ? <FilesBrowser onOpenQueue={() => setTab("queue")} />
        : <div className={`flex-1 min-h-0 overflow-auto p-4 ${t.panel}`}><QueuePanel /></div>}
    </div>
  );
}
