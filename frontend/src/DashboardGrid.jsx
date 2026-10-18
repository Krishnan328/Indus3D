import React, { useState, useMemo, useEffect } from "react";
import { Activity, GripHorizontal, Lock, Unlock, PlaySquare } from "lucide-react";
import { useStore } from "./store";
import { Viewport } from "./Viewport";
import { PrintStatusCard } from "./PrintStatusCard";
import { QualityPanel } from "./QualityPanel";
import { ActionLog } from "./ActionLog";
import { CameraFeeds } from "./CameraFeeds";
import { TemperatureChart } from "./TemperatureChart";
import { ToolheadControls } from "./ToolheadControls";
import { VibrationPanel } from "./VibrationPanel";

import { useThemeTokens, useIsBrutalist } from "./theme";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const ResponsiveGridLayout = WidthProvider(Responsive);

// ── Macros Card ──────────────────────────────────────────────────────────────
export function MacrosCard({ isDarkMode }) {
  const macros = useStore((s) => s.macros);
  const sendGcode = useStore((s) => s.sendGcode);
  const hiddenMacros = useStore((s) => s.uiPrefs.hiddenMacros);
  const macroOrder = useStore((s) => s.uiPrefs.macroOrder);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const visibleMacros = useMemo(() => {
    const all = (macros || []).filter(m => typeof m === "string" && !m.startsWith("_"));
    const hiddenSet = new Set(hiddenMacros || []);
    const shown = all.filter(m => !hiddenSet.has(m));
    if (!macroOrder || !macroOrder.length) return shown;
    // Explicitly ordered macros first (in the configured order), then any
    // remaining ones (new macros added in Klipper since the order was set,
    // or ones simply never reordered) in their natural order.
    const orderIndex = new Map(macroOrder.map((m, i) => [m, i]));
    const ordered = shown.filter(m => orderIndex.has(m)).sort((a, b) => orderIndex.get(a) - orderIndex.get(b));
    const rest = shown.filter(m => !orderIndex.has(m));
    return [...ordered, ...rest];
  }, [macros, hiddenMacros, macroOrder]);

  return (
    <div className={`h-full flex flex-col p-3 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-2 shrink-0">
        <PlaySquare size={16} className={brutalist ? "" : "text-blue-500"} />
        <h3 className={t.heading}>Macros</h3>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {!visibleMacros.length ? (
          <div className="text-xs text-gray-500 opacity-60 italic flex items-center justify-center h-full text-center px-4">
            {(macros || []).filter(m => typeof m === "string" && !m.startsWith("_")).length > 0
              ? "All macros are hidden — check Settings → Macros."
              : "No macros found in Klipper."}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {visibleMacros.map((macro) => (
              <button
                key={macro}
                onClick={() => sendGcode(macro)}
                className={`px-2 py-2 text-[10px] sm:text-xs font-bold tracking-wide uppercase rounded flex items-center justify-center transition-transform active:scale-95 ${
                  brutalist
                    ? "bg-[#FFE9A8] border-2 border-[#111] text-[#111] hover:bg-[#FFD166]"
                    : isDarkMode
                      ? "bg-gray-800 text-gray-200 hover:bg-gray-700 border border-gray-700"
                      : "bg-white text-gray-700 shadow-sm border border-gray-300 hover:bg-gray-50"
                }`}
              >
                {macro}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── LED Quick Control Card ───────────────────────────────────────────────────
export function LedControlCard({ isDarkMode }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const ledProfile = useStore((s) => s.ledProfile);
  const fetchLedProfile = useStore((s) => s.fetchLedProfile);
  const applyLedProfileState = useStore((s) => s.applyLedProfileState);
  const turnLedsOff = useStore((s) => s.turnLedsOff);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { fetchLedProfile(); }, [fetchLedProfile]);

  const btnCls = brutalist
    ? "bg-[#FFE9A8] border-2 border-[#111] text-[#111] hover:bg-[#FFD166]"
    : isDarkMode
      ? "bg-gray-800 text-gray-200 hover:bg-gray-700 border border-gray-700"
      : "bg-white text-gray-700 shadow-sm border border-gray-300 hover:bg-gray-50";

  const quickApply = async (state) => {
    setBusy(state);
    setMsg("");
    const result = state === "off" ? await turnLedsOff() : await applyLedProfileState(state);
    if (result.error) setMsg(result.error);
    setBusy(null);
  };

  const configured = ledProfile.led_names && ledProfile.led_names.length > 0;

  return (
    <div className={`h-full flex flex-col p-3 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-2 shrink-0">
        <span className="text-base leading-none">💡</span>
        <h3 className={t.heading}>LEDs</h3>
        {ledProfile.enabled && (
          <span className={`ml-auto text-[9px] px-2 py-0.5 rounded-full ${brutalist ? "bg-emerald-300 border border-[#111]" : "bg-emerald-500/20 text-emerald-500"}`}>
            AUTO
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {!configured ? (
          <div className="text-xs text-gray-500 opacity-60 italic flex items-center justify-center h-full text-center px-4">
            No LEDs configured yet — set up in Settings → LEDs.
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[["idle", "Idle"], ["printing", "Printing"], ["complete", "Complete"], ["off", "Off"]].map(([key, label]) => (
              <button
                key={key}
                onClick={() => quickApply(key)}
                disabled={busy === key}
                className={`px-2 py-2 text-[10px] sm:text-xs font-bold tracking-wide uppercase rounded flex items-center justify-center transition-transform active:scale-95 disabled:opacity-40 ${btnCls}`}
              >
                {busy === key ? "…" : label}
              </button>
            ))}
          </div>
        )}
        {msg && <div className="mt-2 text-[10px] text-red-500">{msg}</div>}
      </div>
    </div>
  );
}


// ── G-Code Terminal ──────────────────────────────────────────────────────────
export function Terminal({ isDarkMode }) {
  const [input, setInput]     = useState("");
  const [isSending, setSend]  = useState(false);
  const [history, setHistory] = useState([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [draft, setDraft]     = useState("");
  const filePosition = useStore((s) => s.telemetry?.file_position);
  const gcodeLines   = useStore((s) => s.gcodeLines);
  const liveCommands = useStore((s) => s.liveCommands);
  const simMode      = useStore((s) => s.simMode);
  const sendGcode    = useStore((s) => s.sendGcode);
  const isPrinting   = useStore((s) => s.telemetry?.state === "printing");
  const uiTheme      = useStore((s) => s.theme);
  const consoleDirection    = useStore((s) => s.uiPrefs.consoleDirection);
  const consoleCompact      = useStore((s) => s.uiPrefs.consoleCompact);
  const hideTempsInConsole  = useStore((s) => s.uiPrefs.hideTempsInConsole);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const displayLines = useMemo(() => {
    const parseLive = (lines) => lines.map(l => {
      const text = l.text ?? l;
      const source = text.startsWith("[QC]") || text.startsWith("[INDUS]") ? "indus" : "user";
      return { text, source, highlight: true };
    });

    if (simMode) {
      const sliced = liveCommands.slice(-6);
      return sliced.map((l, i) => {
        const text = l.text ?? l;
        let source = "file";
        if (text.startsWith("[QC]") || text.startsWith("[INDUS]")) source = "indus";
        if (text.startsWith(">>> ")) source = "user";

        return {
          text,
          source,
          highlight: false,
          active: i === sliced.length - 1
        };
      });
    }
    if (!isPrinting) return [];

    const recentLive = parseLive(liveCommands.slice(-3));

    if (!gcodeLines?.length) {
      if (recentLive.length) return recentLive;
      return [{ text: "; Loading G-code file...", source: "file" }];
    }

    try {
      let lo = 0, hi = gcodeLines.length - 1, mid = 0;
      const pos = Number(filePosition) || 0;
      while (lo <= hi) {
        mid = Math.floor((lo + hi) / 2);
        if (!gcodeLines[mid]) break;
        if (gcodeLines[mid].byte < pos)       lo = mid + 1;
        else if (gcodeLines[mid].byte > pos)  hi = mid - 1;
        else break;
      }
      const start = Math.max(0, mid - 2);
      const end   = Math.min(gcodeLines.length, mid + 3);
      const fileLines = gcodeLines.slice(start, end).map((l, i) => ({
        text: l?.text || ";",
        active: (start + i) === mid,
        source: "file"
      }));
      return [...recentLive, ...fileLines];
    } catch {
      return recentLive;
    }
  }, [filePosition, gcodeLines, liveCommands, simMode, isPrinting]);

  // Console filter: hide M105-style temperature status lines (e.g. "ok T:210.0 /210.0 B:60.0 /60.0")
  const filteredLines = useMemo(() => {
    if (!hideTempsInConsole) return displayLines;
    const tempLine = /(^|\s)(B|T\d*):-?\d/;
    return displayLines.filter((l) => !tempLine.test(l.text || ""));
  }, [displayLines, hideTempsInConsole]);

  const send = async (e) => {
    e.preventDefault();
    const cmd = input.trim();
    if (!cmd) return;
    setSend(true);
    await sendGcode(cmd);
    setHistory(prev => [cmd, ...prev]);
    setHistoryIdx(-1);
    setDraft("");
    setInput("");
    setSend(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (historyIdx < history.length - 1) {
        if (historyIdx === -1) setDraft(input);
        const nextIdx = historyIdx + 1;
        setHistoryIdx(nextIdx);
        setInput(history[nextIdx]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIdx > 0) {
        const prevIdx = historyIdx - 1;
        setHistoryIdx(prevIdx);
        setInput(history[prevIdx]);
      } else if (historyIdx === 0) {
        setHistoryIdx(-1);
        setInput(draft);
      }
    }
  };

  let termBgClass = isDarkMode ? "bg-black border border-gray-800 rounded-lg text-gray-500" : "bg-gray-100 border border-gray-300 rounded-lg text-gray-400";
  let termActiveClass = isDarkMode ? "text-green-400 font-bold" : "text-green-700 font-bold";
  let termUserClass = isDarkMode ? "text-blue-400 font-bold" : "text-blue-600 font-bold";
  let termIndusClass = isDarkMode ? "text-orange-400 font-bold" : "text-orange-600 font-bold";
  let inputCls = isDarkMode ? "bg-gray-900 text-green-400 border border-gray-700 rounded-lg" : "bg-white text-gray-800 border border-gray-300 rounded-lg";
  let btnCls = isDarkMode ? "bg-blue-600 text-white rounded-lg" : "bg-blue-600 text-white rounded-lg";

  if (uiTheme === "creme") {
     termBgClass = "bg-[#F5F0E8] border-2 border-[#E8DFD0] rounded-lg text-emerald-700/60";
     termActiveClass = "text-emerald-600 font-bold";
     termUserClass = "text-blue-600 font-bold";
     termIndusClass = "text-orange-600 font-bold";
     inputCls = "bg-white text-emerald-700 border border-[#E8DFD0] rounded-lg";
     btnCls = "bg-emerald-600 text-white rounded-lg hover:bg-emerald-700";
  } else if (uiTheme === "blueprint") {
     termBgClass = "bg-[#d0e3ff] border-[3px] border-[#103b8c] text-[#103b8c]/60";
     termActiveClass = "text-black font-bold";
     termUserClass = "text-blue-800 font-bold";
     termIndusClass = "text-orange-600 font-bold";
     inputCls = "bg-[#d0e3ff] text-black border-[3px] border-[#103b8c] rounded-none placeholder-[#103b8c]/50";
     btnCls = "bg-[#103b8c] text-white rounded-none border-[3px] border-[#103b8c] hover:bg-black";
  } else if (uiTheme === "workshop") {
     termBgClass = "bg-[#FDFBF7] border-[3px] border-[#111] text-[#111]/50";
     termActiveClass = "text-black font-bold";
     termUserClass = "text-blue-700 font-bold";
     termIndusClass = "text-orange-600 font-bold";
     inputCls = "bg-[#FDFBF7] text-black border-[3px] border-[#111] rounded-none";
     btnCls = "bg-[#FFD166] text-[#111] font-bold rounded-none border-[3px] border-[#111] hover:bg-yellow-400";
  }

  const getLineClass = (l) => {
    if (l.active) return termActiveClass;
    if (l.source === "user") return termUserClass;
    if (l.source === "indus") return termIndusClass;
    return "";
  };

  const lineClass = consoleCompact ? "whitespace-nowrap px-1 py-0" : "whitespace-nowrap px-1 py-0.5";
  const consoleBody = (
    <div className={`flex-1 min-h-0 p-2 font-mono text-[10px] overflow-y-auto flex ${consoleDirection === "bottom" ? "flex-col" : "flex-col-reverse"} ${consoleCompact ? "gap-0" : ""} ${termBgClass}`}>
      {!filteredLines.length
        ? <div className="text-center italic opacity-40 self-center">
            {isPrinting || simMode ? "; Awaiting G-code..." : "Awaiting Print Job..."}
          </div>
        : (consoleDirection === "bottom" ? filteredLines : [...filteredLines].reverse()).map((l, i) => (
            <div key={i} className={`${lineClass} ${getLineClass(l)}`}>
              {l.text || ";"}
            </div>
          ))
      }
    </div>
  );
  const consoleForm = (
    <form onSubmit={send} className="flex gap-2 shrink-0">
      <input
        type="text"
        value={input}
        onChange={(e) => {
           setInput(e.target.value.toUpperCase());
           if (historyIdx === -1) setDraft(e.target.value.toUpperCase());
        }}
        onKeyDown={handleKeyDown}
        placeholder={simMode ? "e.g. G28 or TEST" : "e.g. G28"}
        disabled={isSending}
        className={`flex-1 px-3 py-1.5 font-mono text-xs outline-none ${inputCls}`}
      />
      <button
        type="submit"
        disabled={isSending || !input.trim()}
        className={`px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-transform active:scale-95 ${btnCls}`}
      >
        Send
      </button>
    </form>
  );

  return (
    <div className={`h-full flex flex-col gap-2 ${consoleCompact ? "p-2" : "p-3"} ${t.panel}`}>
      <div className="flex items-center gap-2 shrink-0">
        <Activity size={15} className={brutalist ? "" : "text-emerald-500"} />
        <h3 className={t.heading}>Console</h3>
        {simMode && <span className={`ml-auto text-[9px] px-2 py-0.5 ${t.chip} ${brutalist ? "bg-[#B7E4C7]" : "bg-blue-700 text-white"}`}>SIM</span>}
      </div>
      {/* "bottom" = shell-style: input above, newest entry at the bottom.
          "top" (default) = input below, newest entry at the top. */}
      {consoleDirection === "bottom" ? (
        <>
          {consoleForm}
          {consoleBody}
        </>
      ) : (
        <>
          {consoleBody}
          {consoleForm}
        </>
      )}
    </div>
  );
}

// ── Dashboard grid ────────────────────────────────────────────────────────────
const DEFAULT_LAYOUTS = {
  lg: [
    { i: "viewport", x: 0, y: 0, w: 8, h: 5 },
    { i: "status", x: 8, y: 0, w: 4, h: 2 },
    { i: "temperature", x: 8, y: 2, w: 4, h: 3 },
    { i: "quality", x: 0, y: 5, w: 3, h: 3 },
    { i: "toolhead", x: 3, y: 5, w: 5, h: 3 },
    { i: "cameras", x: 8, y: 5, w: 4, h: 3 },
    { i: "terminal", x: 0, y: 8, w: 6, h: 3 },
    { i: "macros", x: 6, y: 8, w: 6, h: 3 },
    { i: "actionlog", x: 0, y: 11, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
  ],
  md: [
    { i: "viewport", x: 0, y: 0, w: 10, h: 5 },
    { i: "status", x: 0, y: 5, w: 5, h: 2 },
    { i: "quality", x: 5, y: 5, w: 5, h: 3 },
    { i: "temperature", x: 0, y: 7, w: 5, h: 3 },
    { i: "toolhead", x: 5, y: 8, w: 5, h: 3 },
    { i: "cameras", x: 0, y: 10, w: 5, h: 3 },
    { i: "terminal", x: 5, y: 11, w: 5, h: 3 },
    { i: "macros", x: 0, y: 13, w: 5, h: 3 },
    { i: "actionlog", x: 5, y: 14, w: 5, h: 3 },
    { i: "leds", x: 0, y: 999, w: 5, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 5, h: 3 },
  ],
  sm: [
    { i: "viewport", x: 0, y: 0, w: 6, h: 6 },
    { i: "status", x: 0, y: 8, w: 6, h: 2 },
    { i: "temperature", x: 0, y: 10, w: 6, h: 2 },
    { i: "quality", x: 0, y: 12, w: 6, h: 3 },
    { i: "toolhead", x: 0, y: 15, w: 6, h: 3 },
    { i: "cameras", x: 0, y: 18, w: 6, h: 3 },
    { i: "terminal", x: 0, y: 21, w: 6, h: 3 },
    { i: "macros", x: 0, y: 24, w: 6, h: 3 },
    { i: "actionlog", x: 0, y: 27, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
  ],
};



const DEFAULT_STATIC_LAYOUTS = {
  lg: [
    { i: "viewport", x: 0, y: 0, w: 4, h: 5 },
    { i: "status", x: 4, y: 0, w: 4, h: 2 },
    { i: "toolhead", x: 8, y: 0, w: 4, h: 3 },
    { i: "temperature", x: 4, y: 2, w: 4, h: 3 },
    { i: "cameras", x: 8, y: 3, w: 4, h: 3 },
    { i: "terminal", x: 0, y: 5, w: 6, h: 4 },
    { i: "macros", x: 6, y: 5, w: 6, h: 4 },
    { i: "actionlog", x: 0, y: 9, w: 12, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
  ],
  md: [
    { i: "viewport", x: 0, y: 0, w: 5, h: 5 },
    { i: "status", x: 5, y: 0, w: 5, h: 2 },
    { i: "toolhead", x: 5, y: 2, w: 5, h: 3 },
    { i: "temperature", x: 0, y: 5, w: 5, h: 3 },
    { i: "cameras", x: 5, y: 5, w: 5, h: 3 },
    { i: "terminal", x: 0, y: 8, w: 5, h: 4 },
    { i: "macros", x: 5, y: 8, w: 5, h: 4 },
    { i: "actionlog", x: 0, y: 12, w: 10, h: 3 },
    { i: "leds", x: 0, y: 999, w: 5, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 5, h: 3 },
  ],
  sm: [
    { i: "viewport", x: 0, y: 0, w: 6, h: 4 },
    { i: "status", x: 0, y: 4, w: 6, h: 2 },
    { i: "temperature", x: 0, y: 6, w: 6, h: 3 },
    { i: "toolhead", x: 0, y: 9, w: 6, h: 3 },
    { i: "cameras", x: 0, y: 12, w: 6, h: 3 },
    { i: "terminal", x: 0, y: 15, w: 6, h: 4 },
    { i: "macros", x: 0, y: 19, w: 6, h: 4 },
    { i: "actionlog", x: 0, y: 23, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
  ],
};

function getSavedLayouts(mode) {
  if (mode === "classic") {
    try {
      const s = localStorage.getItem("indus3d_layout_static_v5");
      if (s) return JSON.parse(s);

      const dyn = localStorage.getItem("indus3d_layout_dynamic_v5");
      if (dyn) {
         const d = JSON.parse(dyn);
         const stat = {};
         for (const bp in d) {
           stat[bp] = Array.isArray(d[bp]) ? d[bp].filter(l => l.i !== "truetwin" && l.i !== "quality" && l.i !== "stats") : [];
         }
         return stat;
      }
    } catch {
      // A stale user layout should never prevent the dashboard from loading.
    }
    return DEFAULT_STATIC_LAYOUTS;
  }

  try {
    const s = localStorage.getItem("indus3d_layout_dynamic_v5");
    if (s) return JSON.parse(s);
  } catch {
    // Fall back to the shipped layout when saved data is unavailable.
  }
  return DEFAULT_LAYOUTS;
}



function CardWrapper({ isLocked, children }) {
  return (
    <div className={`h-full w-full bg-white dark:bg-[#111] rounded-xl overflow-hidden flex flex-col relative group ${!isLocked ? "ring-2 ring-emerald-500/50" : ""}`}>
      {!isLocked && (
        <div className="absolute top-0 left-0 right-0 h-6 bg-emerald-500/10 cursor-move drag-handle z-50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <GripHorizontal size={14} className="text-emerald-500" />
        </div>
      )}
      <div className={`flex-1 min-h-0 ${!isLocked ? "mt-6 pointer-events-none" : ""}`}>
        {children}
      </div>
    </div>
  );
}

export function DashboardGrid({ isDarkMode }) {
  const dashboardMode = useStore((s) => s.dashboardMode);
  const [layouts, setLayouts] = useState(() => getSavedLayouts(dashboardMode));
  const [isLocked, setIsLocked] = useState(true);

  const onLayoutChange = (_layout, allLayouts) => {
    // Prevent React infinite update loops by deep comparing layouts.
    if (JSON.stringify(allLayouts) !== JSON.stringify(layouts)) {
      setLayouts(allLayouts);
      localStorage.setItem(dashboardMode === "classic" ? "indus3d_layout_static_v5" : "indus3d_layout_dynamic_v5", JSON.stringify(allLayouts));
    }
  };

  const resetLayout = () => {
    if (dashboardMode === "classic") {
      localStorage.removeItem("indus3d_layout_static_v5");
      setLayouts(DEFAULT_STATIC_LAYOUTS);
    } else {
      localStorage.removeItem("indus3d_layout_dynamic_v5");
      setLayouts(DEFAULT_LAYOUTS);
    }
  };

  const safeLayouts = layouts && typeof layouts === "object"
    ? layouts
    : dashboardMode === "classic" ? DEFAULT_STATIC_LAYOUTS : DEFAULT_LAYOUTS;

  return (
      <div className="flex-1 min-h-0 overflow-y-auto pr-1 flex flex-col">
        <div className="flex justify-end gap-2 mb-2 shrink-0">
          {!isLocked && (
            <button onClick={resetLayout} className="text-xs px-2 py-1 rounded bg-red-500/20 text-red-500 hover:bg-red-500/40">
              Reset Default Layout
            </button>
          )}
          <button
            onClick={() => setIsLocked(!isLocked)}
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${isLocked ? 'bg-gray-500/10 text-gray-400 hover:bg-gray-500/20' : 'bg-emerald-500 text-white'}`}
          >
            {isLocked ? <><Lock size={12}/> Unlock Dashboard</> : <><Unlock size={12}/> Lock Layout</>}
          </button>
        </div>

        <div className="flex-1 min-h-0 pb-10">
          <ResponsiveGridLayout
            className="layout"
            layouts={safeLayouts}
            breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
            cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
            rowHeight={85}
            onLayoutChange={onLayoutChange}
            draggableHandle=".drag-handle"
            isDraggable={!isLocked}
            isResizable={!isLocked}
            margin={[12, 12]}
          >
            <div key="viewport"><CardWrapper isLocked={isLocked}><Viewport isDarkMode={isDarkMode} /></CardWrapper></div>

            <div key="status"><CardWrapper isLocked={isLocked}><PrintStatusCard isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="temperature"><CardWrapper isLocked={isLocked}><TemperatureChart /></CardWrapper></div>
            {dashboardMode !== "classic" && <div key="quality"><CardWrapper isLocked={isLocked}><QualityPanel isDarkMode={isDarkMode} /></CardWrapper></div>}
            <div key="toolhead"><CardWrapper isLocked={isLocked}><ToolheadControls /></CardWrapper></div>
            <div key="cameras"><CardWrapper isLocked={isLocked}><CameraFeeds isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="terminal"><CardWrapper isLocked={isLocked}><Terminal isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="macros"><CardWrapper isLocked={isLocked}><MacrosCard isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="leds"><CardWrapper isLocked={isLocked}><LedControlCard isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="actionlog"><CardWrapper isLocked={isLocked}><ActionLog isDarkMode={isDarkMode} /></CardWrapper></div>
            <div key="vibration"><CardWrapper isLocked={isLocked}><VibrationPanel /></CardWrapper></div>
          </ResponsiveGridLayout>
        </div>
      </div>
  );
}
