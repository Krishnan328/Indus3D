import React, { useState } from "react";
import { FolderPlus, Upload, RefreshCw, Search, List, LayoutGrid, SlidersHorizontal, ChevronRight, Zap, HardDrive } from "lucide-react";
import { breadcrumbs } from "./filesLogic";
import { Btn } from "./ui";
import { useUi } from "./useUi";

export function RootTabs({ roots, active, dropRoot, onPick, onDragOverRoot, onDragLeaveRoot, onDropRoot }) {
  const u = useUi();
  return (
    <div role="tablist" aria-label="File roots" className="flex items-center gap-1 overflow-x-auto">
      {roots.map((r) => (
        <button key={r.name} type="button" role="tab" aria-selected={r.name === active} onClick={() => onPick(r.name)}
          onDragOver={(e) => onDragOverRoot(e, r)} onDragLeave={onDragLeaveRoot} onDrop={(e) => onDropRoot(e, r)}
          title={r.writable ? r.name : `${r.name} (read-only)`}
          className={`px-3 py-1.5 text-xs whitespace-nowrap transition-colors ${u.brutalist ? "font-mono border-2 border-[#111]" : "rounded-md"}
            ${r.name === active ? (u.brutalist ? "bg-[#111] text-white" : "bg-white/15 font-bold") : "opacity-70 hover:opacity-100 hover:bg-white/5"}
            ${dropRoot === r.name ? "outline outline-2 outline-emerald-400" : ""}`}>
          {r.name}{!r.writable && <span className="ml-1 opacity-60 text-[9px]">ro</span>}
        </button>
      ))}
    </div>
  );
}

export function Breadcrumbs({ root, path, dropPath, onGo, onDragOverCrumb, onDragLeaveCrumb, onDropCrumb }) {
  const crumbs = breadcrumbs(root, path);
  return (
    <nav aria-label="Folder path" className="flex items-center flex-wrap gap-0.5 text-xs font-mono min-w-0">
      {crumbs.map((c, i) => (
        <React.Fragment key={c.path || "root"}>
          {i > 0 && <ChevronRight size={12} className="opacity-40" />}
          <button type="button" onClick={() => onGo(c.path)} aria-current={i === crumbs.length - 1 ? "page" : undefined}
            onDragOver={(e) => onDragOverCrumb(e, c.path)} onDragLeave={onDragLeaveCrumb} onDrop={(e) => onDropCrumb(e, c.path)}
            className={`px-1.5 py-0.5 rounded hover:bg-white/10 truncate max-w-[14rem] ${i === crumbs.length - 1 ? "font-bold" : "opacity-70"}
              ${dropPath === c.path ? "outline outline-2 outline-emerald-400" : ""}`}>
            {c.label}
          </button>
        </React.Fragment>
      ))}
    </nav>
  );
}

const FILTER_LABELS = [
  ["hidden", "Hidden files (.name)"],
  ["backups", "Backup files (Klipper, Moonraker, Crowsnest)"],
  ["temp", "Temporary upload files"],
  ["logs", "Rolled log files"],
  ["printed", "Files already printed"],
];

export function FilterMenu({ filters, onChange }) {
  const [open, setOpen] = useState(false);
  const u = useUi();
  return (
    <div className="relative">
      <Btn onClick={() => setOpen(!open)} aria-haspopup="true" aria-expanded={open} title="Show or hide kinds of files"><SlidersHorizontal size={12} /> Filters</Btn>
      {open && (
        <div className={`absolute right-0 top-full mt-1 z-30 p-2 w-72 text-xs space-y-1 ${u.menu}`} onMouseLeave={() => setOpen(false)}>
          <div className="text-[10px] uppercase tracking-widest opacity-60 mb-1">Show</div>
          {FILTER_LABELS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={!!filters[k]} onChange={(e) => onChange({ ...filters, [k]: e.target.checked })} /> {label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function DiskBar({ usage }) {
  if (!usage || usage.percent == null) return null;
  const tone = usage.percent >= 95 ? "bg-red-500" : usage.percent >= 85 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2 text-[10px] opacity-80" title={`${Math.round(usage.used / 1048576)} MB of ${Math.round(usage.total / 1048576)} MB used`}>
      <HardDrive size={12} />
      <div className="w-24 h-1.5 bg-black/30 overflow-hidden"><div className={`h-full ${tone}`} style={{ width: `${Math.min(100, usage.percent)}%` }} /></div>
      <span>{usage.percent}% used</span>
    </div>
  );
}

export function Toolbar({ search, onSearch, searchRef, view, onView, thumb, onThumb, filters, onFilters, canWrite, loading,
  onMkdir, onUpload, onRefresh, onFinder, hasMeta }) {
  const u = useUi();
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative flex-1 min-w-[10rem] max-w-xs">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 opacity-50" />
        <input ref={searchRef} value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Filter this folder  ( / )" aria-label="Filter this folder"
          className={`w-full pl-7 pr-2 py-1.5 text-xs outline-none ${u.input}`} />
      </div>
      <Btn onClick={onFinder} title="Go to file (Ctrl+P)"><Zap size={12} /> Go to file</Btn>
      <div className="ml-auto flex items-center gap-2 flex-wrap">
        {view === "grid" || hasMeta ? (
          <label className="flex items-center gap-1 text-[10px] opacity-70">Thumbnails
            <input type="range" min={24} max={160} step={8} value={thumb} onChange={(e) => onThumb(Number(e.target.value))} aria-label="Thumbnail size" className="w-20" /></label>
        ) : null}
        <div className="flex" role="group" aria-label="View">
          <Btn onClick={() => onView("list")} aria-pressed={view === "list"} title="List" className={view === "list" ? "bg-white/15" : ""}><List size={12} /></Btn>
          <Btn onClick={() => onView("grid")} aria-pressed={view === "grid"} title="Grid" className={view === "grid" ? "bg-white/15" : ""}><LayoutGrid size={12} /></Btn>
        </div>
        <FilterMenu filters={filters} onChange={onFilters} />
        <Btn onClick={onMkdir} disabled={!canWrite} title={canWrite ? "New folder" : "Read-only root"}><FolderPlus size={12} /> New folder</Btn>
        <Btn onClick={onUpload} disabled={!canWrite} title={canWrite ? "Upload files (or drop them here)" : "Read-only root"}><Upload size={12} /> Upload</Btn>
        <Btn onClick={onRefresh} aria-label="Refresh"><RefreshCw size={12} className={loading ? "animate-spin" : ""} /></Btn>
      </div>
    </div>
  );
}
