import React from "react";
import { Keyboard, X, ShieldAlert, Navigation, Move, Terminal } from "lucide-react";
import { useThemeTokens, useIsBrutalist } from "./theme";

export function ShortcutsModal({ isOpen, onClose }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  if (!isOpen) return null;

  const sections = [
    {
      title: "Safety & Emergency",
      icon: ShieldAlert,
      color: "text-red-400",
      items: [
        { key: "Space", desc: "Emergency Stop (E-Stop confirmation dialog)" },
        { key: "Esc", desc: "Close any open dialog or modal" },
      ],
    },
    {
      title: "Console & Terminal",
      icon: Terminal,
      color: "text-blue-400",
      items: [
        { key: "Ctrl + K / /", desc: "Focus G-code console input" },
        { key: "Tab", desc: "Command autocomplete / next suggestion" },
        { key: "↑ / ↓", desc: "Browse command history or suggestion list" },
      ],
    },
    {
      title: "Navigation",
      icon: Navigation,
      color: "text-emerald-400",
      items: [
        { key: "1", desc: "Switch to Dashboard" },
        { key: "2", desc: "Switch to Fleet Command" },
        { key: "3", desc: "Switch to Digital Twin" },
        { key: "4", desc: "Switch to Printer Lab" },
        { key: "5", desc: "Switch to Files" },
        { key: "6", desc: "Switch to Print History" },
        { key: "7", desc: "Switch to System" },
        { key: "?", desc: "Open this keyboard shortcuts cheat-sheet" },
      ],
    },
    {
      title: "Toolhead Jogging (When Idle)",
      icon: Move,
      color: "text-purple-400",
      items: [
        { key: "Alt + ← / →", desc: "Jog X axis (-10mm / +10mm)" },
        { key: "Alt + ↑ / ↓", desc: "Jog Y axis (+10mm / -10mm)" },
        { key: "PageUp / PageDn", desc: "Jog Z axis (+1mm / -1mm)" },
      ],
    },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
      <div className={`max-w-xl w-full p-6 rounded-2xl flex flex-col gap-4 border shadow-2xl ${t.panel}`}>
        <div className="flex items-center justify-between pb-2 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            <Keyboard size={20} className="text-blue-400" />
            <h3 className="font-bold text-sm text-gray-100 uppercase tracking-wide">
              Keyboard Shortcuts
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded opacity-60 hover:opacity-100 text-gray-400 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[70vh] overflow-y-auto pr-1">
          {sections.map((sec, idx) => {
            const Icon = sec.icon;
            return (
              <div key={idx} className="flex flex-col gap-2">
                <div className={`flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider ${sec.color}`}>
                  <Icon size={14} />
                  <span>{sec.title}</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {sec.items.map((it, i) => (
                    <div
                      key={i}
                      className="p-2 rounded bg-black/30 border border-white/5 flex items-center justify-between text-xs font-mono"
                    >
                      <span className="opacity-80 text-[11px] font-sans">{it.desc}</span>
                      <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-white font-bold text-[10px] shrink-0 border border-white/10 shadow-sm ml-2">
                        {it.key}
                      </kbd>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end pt-2 border-t border-white/10">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-white/10 hover:bg-white/20 text-white transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
