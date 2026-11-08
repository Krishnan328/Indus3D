import React from "react";
import { Folder, FileText, Layers, Image as ImageIcon, Film, ArrowUp, ChevronUp, ChevronDown, FileArchive, FileQuestion, History } from "lucide-react";
import { fileKind, formatBytes, formatDuration } from "./filesLogic";
import { gridTemplate, cellText } from "./columns";

export function KindIcon({ entry, size = 16 }) {
  if (entry.type === "dir") return <Folder size={size} className="text-amber-400" />;
  switch (fileKind(entry.name)) {
    case "gcode": return <Layers size={size} className="opacity-60" />;
    case "image": return <ImageIcon size={size} className="opacity-60" />;
    case "video": return <Film size={size} className="opacity-60" />;
    case "archive": return <FileArchive size={size} className="opacity-60" />;
    case "other": return <FileQuestion size={size} className="opacity-40" />;
    default: return <FileText size={size} className="opacity-60" />;
  }
}

export function Thumb({ entry, src, size }) {
  return (
    <div className="shrink-0 flex items-center justify-center overflow-hidden bg-black/10 rounded" style={{ width: size, height: size }}>
      {src ? <img src={src} alt="" loading="lazy" className="w-full h-full object-cover" /> : <KindIcon entry={entry} size={Math.max(14, size / 2.5)} />}
    </div>
  );
}

export function ListHeader({ cols, sort, onSort }) {
  return (
    <div role="row" className="grid items-center gap-2 px-2 py-1.5 text-[10px] uppercase tracking-wider opacity-70 sticky top-0 z-10 bg-inherit border-b border-white/10"
      style={{ gridTemplateColumns: gridTemplate(cols) }}>
      <span />
      {cols.map((c) => {
        const active = sort.key === c.key;
        return (
          <button key={c.key} type="button" role="columnheader" onClick={() => onSort(c.key)} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
            className={`flex items-center gap-0.5 hover:opacity-100 ${c.align === "right" ? "justify-end" : ""} ${active ? "opacity-100 font-bold" : ""}`}>
            {c.label}{active && (sort.dir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
          </button>
        );
      })}
    </div>
  );
}

// One row. Handlers get the entry; the row itself holds no state so a long list stays cheap.
function RowImpl({ entry, cols, selected, dropTarget, active, thumbSrc, thumbSize, showThumb, dateFormat, handlers }) {
  const { onClick, onOpen, onContext, onDragStart, onDragOver, onDragLeave, onDrop, onToggle } = handlers;
  return (
    <div role="row" aria-selected={selected} tabIndex={-1} draggable
      data-path={entry.path}
      onClick={(e) => onClick(e, entry)} onDoubleClick={() => onOpen(entry)} onContextMenu={(e) => onContext(e, entry)}
      onDragStart={(e) => onDragStart(e, entry)} onDragOver={(e) => onDragOver(e, entry)} onDragLeave={onDragLeave} onDrop={(e) => onDrop(e, entry)}
      className={`grid items-center gap-2 px-2 py-1 text-xs cursor-default select-none border-b border-white/5
        ${selected ? "bg-sky-500/20" : "hover:bg-white/5"} ${dropTarget ? "outline outline-2 outline-emerald-400 -outline-offset-2" : ""}`}
      style={{ gridTemplateColumns: gridTemplate(cols) }}>
      <input type="checkbox" checked={selected} onChange={() => onToggle(entry)} onClick={(e) => e.stopPropagation()} aria-label={`Select ${entry.name}`} />
      {cols.map((c) => {
        if (c.key === "name") {
          return (
            <div key="name" role="gridcell" className="flex items-center gap-2 min-w-0">
              {showThumb && entry.type === "file" ? <Thumb entry={entry} src={thumbSrc} size={thumbSize} /> : <KindIcon entry={entry} />}
              <span className="truncate font-mono" title={entry.name}>{entry.name}</span>
              {active && <span className="shrink-0 text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-600 text-white">printing</span>}
              {entry.type === "file" && entry.meta?.print_start_time && <History size={10} className="shrink-0 opacity-40" aria-label="printed before" />}
              {entry.type === "file" && entry.hasMeta === false && fileKind(entry.name) === "gcode" && (
                <span className="shrink-0 text-[9px] opacity-50" title="No slicer metadata yet">no metadata</span>)}
            </div>
          );
        }
        return <div key={c.key} role="gridcell" className={`truncate opacity-80 ${c.align === "right" ? "text-right" : ""}`}>{cellText(entry, c.key, dateFormat)}</div>;
      })}
    </div>
  );
}
export const ListRow = React.memo(RowImpl);

export function ParentRow({ cols, dropTarget, onOpen, onDragOver, onDragLeave, onDrop }) {
  return (
    <div role="row" onDoubleClick={onOpen} onClick={onOpen} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
      className={`grid items-center gap-2 px-2 py-1 text-xs cursor-pointer border-b border-white/5 hover:bg-white/5 ${dropTarget ? "outline outline-2 outline-emerald-400 -outline-offset-2" : ""}`}
      style={{ gridTemplateColumns: gridTemplate(cols) }}>
      <span />
      <div className="flex items-center gap-2"><ArrowUp size={14} className="opacity-60" /><span className="font-mono">..</span></div>
    </div>
  );
}

export function GridCard({ entry, selected, dropTarget, active, thumbSrc, thumbSize, handlers }) {
  const { onClick, onOpen, onContext, onDragStart, onDragOver, onDragLeave, onDrop } = handlers;
  const box = Math.max(64, thumbSize * 1.4);
  return (
    <div role="gridcell" aria-selected={selected} draggable data-path={entry.path}
      onClick={(e) => onClick(e, entry)} onDoubleClick={() => onOpen(entry)} onContextMenu={(e) => onContext(e, entry)}
      onDragStart={(e) => onDragStart(e, entry)} onDragOver={(e) => onDragOver(e, entry)} onDragLeave={onDragLeave} onDrop={(e) => onDrop(e, entry)}
      className={`flex flex-col items-center gap-1 p-2 text-[11px] cursor-default select-none rounded ${selected ? "bg-sky-500/20" : "hover:bg-white/5"} ${dropTarget ? "outline outline-2 outline-emerald-400" : ""}`}
      style={{ width: box + 20 }}>
      <div className="relative">
        <Thumb entry={entry} src={entry.type === "file" ? thumbSrc : null} size={box} />
        {active && <span className="absolute top-1 left-1 text-[9px] px-1.5 rounded-full bg-emerald-600 text-white">printing</span>}
      </div>
      <span className="w-full text-center truncate font-mono" title={entry.name}>{entry.name}</span>
      <span className="opacity-50 text-[10px]">{entry.type === "dir" ? "folder" : [formatBytes(entry.size), formatDuration(entry.meta?.estimated_time)].filter(Boolean).join(" · ")}</span>
    </div>
  );
}
