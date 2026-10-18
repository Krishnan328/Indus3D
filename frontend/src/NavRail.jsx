import React from "react";
import { LayoutDashboard, GitBranch, Files, FileText, Map, Settings, Sparkles, Layers, Power, FileDown, Database } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

const PAGE_IDS = ["dashboard", "twin", "files", "fleet"];

export function NavRail({ page, setPage, onOpenEditor, onOpenHeightmap, onOpenSettings, onOpenCalibration, onOpenPower, onOpenSpools }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const items = [
    { id: "dashboard", icon: LayoutDashboard, label: "Dashboard", onClick: () => setPage("dashboard") },
    { id: "fleet",      icon: Layers,          label: "Fleet Command", onClick: () => setPage("fleet") },
    { id: "twin",       icon: GitBranch,       label: "Digital Twin", onClick: () => setPage("twin") },
    { id: "files",      icon: Files,           label: "Files", onClick: () => setPage("files") },
    { id: "config",     icon: FileText,        label: "Config editor", onClick: onOpenEditor },
    { id: "heightmap",  icon: Map,             label: "Heightmap", onClick: onOpenHeightmap },
    { id: "calibration", icon: Sparkles,       label: "Guided calibration", onClick: onOpenCalibration },
    { id: "spools",     icon: Database,        label: "Virtual Spool Manager", onClick: onOpenSpools },
    { id: "settings",   icon: Settings,        label: "Settings", onClick: onOpenSettings },
  ];
  const inactiveBg = brutalist ? "bg-white" : soft ? "hover:bg-black/[0.04]" : "hover:bg-white/5";


  return (
    <div className={`flex flex-col items-center gap-2 py-4 px-2 w-16 shrink-0 ${t.panelSolid}`}>
      {items.map((item) => {
        const active = PAGE_IDS.includes(item.id) && item.id === page;
        const IconComponent = item.icon;
        return (
          <button
            key={item.id}
            onClick={item.onClick}
            title={item.label}
            className={`w-11 h-11 flex items-center justify-center transition-colors
              ${brutalist ? "rounded-none border-2 border-[#111]" : "rounded-xl"}
              ${active ? t.railBtnActive : `${t.railBtn} ${inactiveBg}`}`}
          >
            <IconComponent size={19} />
          </button>
        );
      })}
      <div className="flex-1" />
      <button
        onClick={() => {
          const exportFn = useStore.getState().exportAnnotatedGcode;
          exportFn();
        }}
        title="Export Annotated G-code (Research)"
        className={`w-11 h-11 flex items-center justify-center transition-colors text-emerald-500
          ${brutalist ? "rounded-none border-2 border-[#111] hover:bg-emerald-500 hover:text-white" : "rounded-xl hover:bg-emerald-500 hover:text-white"}`}
      >
        <FileDown size={19} />
      </button>
      <button
        onClick={onOpenPower}
        title="Power & Host Control"
        className={`w-11 h-11 flex items-center justify-center transition-colors text-red-500
          ${brutalist ? "rounded-none border-2 border-[#111] hover:bg-red-500 hover:text-white" : "rounded-xl hover:bg-red-500 hover:text-white"}`}
      >
        <Power size={19} />
      </button>
    </div>
  );
}
