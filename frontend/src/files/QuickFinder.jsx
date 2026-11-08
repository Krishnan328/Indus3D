import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useStore } from "../store";
import { fuzzyFilter, baseName, parentPath, fileKind } from "./filesLogic";
import { Modal } from "./ui";
import { useUi } from "./useUi";

// "Go to file" (Ctrl+P): fuzzy search across every file in the current root. The flat list is fetched once
// when the finder opens (the server caches it for a few seconds).
export function QuickFinder({ root, onPick, onClose }) {
  const u = useUi();
  const load = useStore((s) => s.fmTreeLoad);
  const [files, setFiles] = useState(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    let alive = true;
    load(root).then((f) => { if (alive) setFiles(f); });
    return () => { alive = false; };
  }, [root, load]);

  const results = useMemo(() => fuzzyFilter(q, files || [], (f) => f.path, 40), [q, files]);
  const idx = Math.min(sel, Math.max(0, results.length - 1));

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel(Math.min(idx + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel(Math.max(idx - 1, 0)); }
    else if (e.key === "Enter" && results[idx]) { e.preventDefault(); onPick(results[idx]); }
  };

  return (
    <Modal title={`Go to file in ${root}`} onClose={onClose}>
      <div className="flex items-center gap-2 mb-3">
        <Search size={14} className="opacity-50" />
        <input ref={inputRef} autoFocus value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} onKeyDown={onKey}
          placeholder="Type part of a file name or path…" aria-label="File name" className={`flex-1 px-2 py-1.5 text-sm outline-none ${u.input}`} />
      </div>
      {files === null ? <div className="opacity-50 text-xs">Loading file list…</div>
        : !results.length ? <div className="opacity-50 text-xs italic">No matching file.</div>
          : (
            <ul role="listbox" className="max-h-80 overflow-auto">
              {results.map((f, i) => (
                <li key={f.path} role="option" aria-selected={i === idx}>
                  <button type="button" onClick={() => onPick(f)} onMouseEnter={() => setSel(i)}
                    className={`w-full text-left px-2 py-1.5 text-xs flex items-baseline gap-2 ${i === idx ? "bg-white/10" : ""}`}>
                    <span className="font-mono truncate">{baseName(f.path)}</span>
                    <span className="opacity-40 truncate">{parentPath(f.path)}</span>
                    <span className="ml-auto opacity-30 text-[10px]">{fileKind(f.path)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
    </Modal>
  );
}
