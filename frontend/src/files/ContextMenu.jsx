import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useUi } from "./useUi";

// Right-click menu. ``items``: [{label, icon, onClick, disabled, danger, hint} | {separator: true}].
// Closes on Escape, outside click, scroll and resize; arrow keys move between enabled items.
export function ContextMenu({ x, y, items, onClose }) {
  const u = useUi();
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: x, top: y });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({
      left: Math.max(4, Math.min(x, window.innerWidth - r.width - 4)),
      top: Math.max(4, Math.min(y, window.innerHeight - r.height - 4)),
    });
  }, [x, y, items]);

  useEffect(() => {
    const close = () => onClose();
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const btns = Array.from(ref.current?.querySelectorAll("button:not(:disabled)") || []);
      if (!btns.length) return;
      const i = btns.indexOf(document.activeElement);
      const next = e.key === "ArrowDown" ? (i + 1) % btns.length : (i - 1 + btns.length) % btns.length;
      btns[next].focus();
    };
    window.addEventListener("mousedown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    ref.current?.querySelector("button:not(:disabled)")?.focus();
    return () => {
      window.removeEventListener("mousedown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [onClose]);

  return (
    <div ref={ref} role="menu" style={{ left: pos.left, top: pos.top }} className={`fixed z-[85] min-w-[200px] py-1 text-xs ${u.menu}`}
      onContextMenu={(e) => e.preventDefault()}>
      {items.map((it, i) => it.separator
        ? <div key={`s${i}`} role="separator" className="my-1 h-px bg-current opacity-15" />
        : (
          <button key={it.label} type="button" role="menuitem" disabled={it.disabled} title={it.hint}
            onClick={() => { onClose(); it.onClick?.(); }}
            className={`w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-white/10 focus:bg-white/10 outline-none disabled:opacity-35 disabled:cursor-not-allowed ${it.danger ? "text-red-400" : ""}`}>
            <span className="w-4 shrink-0 flex justify-center">{it.icon}</span>
            <span className="flex-1">{it.label}</span>
            {it.shortcut && <span className="opacity-40 text-[10px]">{it.shortcut}</span>}
          </button>
        ))}
    </div>
  );
}
