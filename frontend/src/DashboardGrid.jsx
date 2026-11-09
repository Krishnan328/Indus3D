import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import {
  Activity, GripHorizontal, Lock, Unlock, PlaySquare, Trash2,
  Cpu, Server, HardDrive, Thermometer,
  Search, X, ChevronDown, BookMarked, Pencil,
} from "lucide-react";
import {
  buildFilterPredicate,
  applyFilter,
  isValidRegex,
  buildCompletionList,
  getCompletions,
  BUILTIN_PRESETS,
  loadFilterMode,
  saveFilterMode,
  loadUserPresets,
  saveUserPresets,
} from "./console/consoleLogic.js";
import { filterMacrosByState, groupMacros, DEFAULT_MACRO_CONFIG } from "./slices/macroSlice";
import { useStore } from "./store";
import { Viewport } from "./Viewport";
import { PrintStatusCard } from "./PrintStatusCard";
import { QualityPanel } from "./QualityPanel";
import { ActionLog } from "./ActionLog";
import { CameraFeeds } from "./CameraFeeds";
import { TemperatureChart } from "./TemperatureChart";
import { ToolheadControls } from "./ToolheadControls";
import { VibrationPanel } from "./VibrationPanel";
import { MoonrakerSensorsCard } from "./MoonrakerSensorsCard";
import { QueueCard } from "./QueueCard";

import { useThemeTokens, useIsBrutalist } from "./theme";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const ResponsiveGridLayout = WidthProvider(Responsive);

// ── Macros Card ──────────────────────────────────────────────────────────────
const MACRO_COLOR_CLASSES = {
  default: "",
  red: "bg-red-700/60 hover:bg-red-600 text-red-100 border-red-600",
  amber: "bg-amber-700/60 hover:bg-amber-600 text-amber-100 border-amber-600",
  green: "bg-green-700/60 hover:bg-green-600 text-green-100 border-green-600",
  blue: "bg-blue-700/60 hover:bg-blue-600 text-blue-100 border-blue-600",
  purple: "bg-purple-700/60 hover:bg-purple-600 text-purple-100 border-purple-600",
};

export function MacrosCard({ isDarkMode }) {
  const macros = useStore((s) => s.macros);
  const runMacro = useStore((s) => s.runMacro);
  const macroStatus = useStore((s) => s.macroStatus);
  const macroConfigs = useStore((s) => s.macroConfigs) || {};
  const setMacroConfig = useStore((s) => s.setMacroConfig);
  const hiddenMacros = useStore((s) => s.uiPrefs.hiddenMacros);
  const macroOrder = useStore((s) => s.uiPrefs.macroOrder);
  const printerState = useStore((s) => s.telemetry?.state) || "idle";
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const [editingMacro, setEditingMacro] = useState(null);
  const [editGroup, setEditGroup] = useState("General");
  const [editColor, setEditColor] = useState("default");
  const [editShowWhen, setEditShowWhen] = useState("always");

  const openConfig = (macroName, e) => {
    e.stopPropagation();
    const cfg = macroConfigs[macroName] || DEFAULT_MACRO_CONFIG;
    setEditingMacro(macroName);
    setEditGroup(cfg.group || "General");
    setEditColor(cfg.color || "default");
    setEditShowWhen(cfg.showWhen || "always");
  };

  const saveConfig = () => {
    if (!editingMacro) return;
    setMacroConfig(editingMacro, {
      group: editGroup.trim() || "General",
      color: editColor,
      showWhen: editShowWhen,
    });
    setEditingMacro(null);
  };

  const visibleMacros = useMemo(() => {
    const all = (macros || []).filter((m) => typeof m === "string" && !m.startsWith("_"));
    const hiddenSet = new Set(hiddenMacros || []);
    const shown = all.filter((m) => !hiddenSet.has(m));
    if (!macroOrder || !macroOrder.length) return shown;
    const orderIndex = new Map(macroOrder.map((m, i) => [m, i]));
    const ordered = shown.filter((m) => orderIndex.has(m)).sort((a, b) => orderIndex.get(a) - orderIndex.get(b));
    const rest = shown.filter((m) => !orderIndex.has(m));
    return [...ordered, ...rest];
  }, [macros, hiddenMacros, macroOrder]);

  // Apply state-based filtering
  const stateFilteredMacros = useMemo(() => {
    return filterMacrosByState(visibleMacros, macroConfigs, printerState);
  }, [visibleMacros, macroConfigs, printerState]);

  // Group macros
  const grouped = useMemo(() => {
    return groupMacros(stateFilteredMacros, macroConfigs);
  }, [stateFilteredMacros, macroConfigs]);

  const groupKeys = useMemo(() => {
    const keys = Object.keys(grouped);
    // Sort so "General" is either first or last, custom groups alphabetical
    return keys.sort((a, b) => {
      if (a === "General") return -1;
      if (b === "General") return 1;
      return a.localeCompare(b);
    });
  }, [grouped]);

  const hasMultipleGroups = groupKeys.length > 1;

  const getMacroButtonClass = (macroName) => {
    const cfg = macroConfigs[macroName] || DEFAULT_MACRO_CONFIG;
    const customColor = MACRO_COLOR_CLASSES[cfg.color];
    if (customColor) return customColor;

    if (brutalist) {
      return "bg-[#FFE9A8] border-2 border-[#111] text-[#111] hover:bg-[#FFD166]";
    }
    if (isDarkMode) {
      return "bg-gray-800 text-gray-200 hover:bg-gray-700 border border-gray-700";
    }
    return "bg-white text-gray-700 shadow-sm border border-gray-300 hover:bg-gray-50";
  };

  return (
    <div className={`h-full flex flex-col p-3 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-2 shrink-0">
        <PlaySquare size={16} className={brutalist ? "" : "text-blue-500"} />
        <h3 className={t.heading}>Macros</h3>
        {macroStatus && (
          <span role="status" className={`ml-auto text-[10px] truncate ${macroStatus.ok ? "text-emerald-500" : "text-red-400"}`}>
            {macroStatus.ok ? "✓" : "✗"} {macroStatus.message}
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-3">
        {!stateFilteredMacros.length ? (
          <div className="text-xs text-gray-500 opacity-60 italic flex items-center justify-center h-full text-center px-4">
            {visibleMacros.length > 0
              ? `No macros visible for state "${printerState}" — check Settings → Macros.`
              : (macros || []).filter((m) => typeof m === "string" && !m.startsWith("_")).length > 0
                ? "All macros are hidden — check Settings → Macros."
                : "No macros found in Klipper."}
          </div>
        ) : (
          groupKeys.map((groupName) => (
            <div key={groupName} className="flex flex-col gap-1.5">
              {hasMultipleGroups && (
                <div className="text-[10px] uppercase font-mono font-bold tracking-wider opacity-50 px-0.5">
                  {groupName}
                </div>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {grouped[groupName].map((macro) => (
                  <div key={macro} className="relative group/btn flex">
                    <button
                      type="button"
                      onClick={() => runMacro(macro)}
                      className={`flex-1 px-2 py-2 text-[10px] sm:text-xs font-bold tracking-wide uppercase rounded flex items-center justify-center transition-transform active:scale-95 border ${getMacroButtonClass(
                        macro
                      )}`}
                    >
                      <span className="truncate">{macro}</span>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => openConfig(macro, e)}
                      title={`Configure ${macro}`}
                      className="absolute right-1 top-1 p-1 rounded bg-black/60 text-white opacity-0 group-hover/btn:opacity-100 hover:scale-110 transition-opacity"
                    >
                      <Pencil size={9} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Macro Config Popover Modal */}
      {editingMacro && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
          <div
            className={`w-full max-w-sm rounded-xl border p-4 shadow-2xl flex flex-col gap-3 font-mono text-xs ${
              isDarkMode ? "bg-gray-900 border-gray-700 text-gray-100" : "bg-white border-gray-300 text-gray-900"
            }`}
          >
            <div className="flex items-center justify-between border-b border-gray-800 pb-2">
              <span className="font-bold text-sm">Configure {editingMacro}</span>
              <button type="button" onClick={() => setEditingMacro(null)} className="p-1 opacity-60 hover:opacity-100">
                <X size={14} />
              </button>
            </div>

            {/* Group */}
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase opacity-60 font-bold">Group</label>
              <input
                type="text"
                value={editGroup}
                onChange={(e) => setEditGroup(e.target.value)}
                placeholder="e.g. Filament, Calibration"
                className={`px-2.5 py-1.5 rounded border outline-none text-xs ${
                  isDarkMode ? "bg-gray-800 border-gray-700" : "bg-gray-50 border-gray-300"
                }`}
              />
            </div>

            {/* Color */}
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase opacity-60 font-bold">Button Color</label>
              <div className="flex items-center gap-2">
                {[
                  { id: "default", bg: "bg-gray-600" },
                  { id: "red", bg: "bg-red-600" },
                  { id: "amber", bg: "bg-amber-600" },
                  { id: "green", bg: "bg-green-600" },
                  { id: "blue", bg: "bg-blue-600" },
                  { id: "purple", bg: "bg-purple-600" },
                ].map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setEditColor(c.id)}
                    className={`w-6 h-6 rounded-full ${c.bg} transition-transform ${
                      editColor === c.id ? "ring-2 ring-white scale-110" : "opacity-70 hover:opacity-100"
                    }`}
                    title={c.id}
                  />
                ))}
              </div>
            </div>

            {/* Show When */}
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase opacity-60 font-bold">Show When</label>
              <select
                value={editShowWhen}
                onChange={(e) => setEditShowWhen(e.target.value)}
                className={`px-2.5 py-1.5 rounded border outline-none text-xs ${
                  isDarkMode ? "bg-gray-800 border-gray-700 text-gray-200" : "bg-gray-50 border-gray-300 text-gray-800"
                }`}
              >
                <option value="always">Always visible</option>
                <option value="idle">Only when Idle</option>
                <option value="printing">Only when Printing</option>
                <option value="paused">Only when Paused</option>
              </select>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-gray-800 mt-1">
              <button
                type="button"
                onClick={() => setEditingMacro(null)}
                className="px-3 py-1.5 rounded border border-gray-700 text-[10px] font-bold uppercase opacity-70 hover:opacity-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveConfig}
                className="px-3 py-1.5 rounded bg-blue-600 text-white text-[10px] font-bold uppercase hover:bg-blue-500"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
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
const COMMON_GCODES = [
  "G28",
  "BED_MESH_CALIBRATE",
  "FIRMWARE_RESTART",
  "M112",
  "M104",
  "M140",
  "M109",
  "M190",
  "M84",
  "QUERY_ENDSTOPS",
  "RESTART"
];

function ConsoleLineRenderer({ line, lineClass, getLineClass, recognizedCommands, onHelpCommand, isDarkMode }) {
  const text = line.text || ";";
  const isKlipperComment = text.startsWith("//");

  if (line.source === "user" && text.startsWith(">>> ")) {
    const afterPrefix = text.slice(4).trim();
    const parts = afterPrefix.split(/\s+/);
    const cmd = parts[0];
    const rest = afterPrefix.slice(cmd.length);

    if (cmd && recognizedCommands.has(cmd.toUpperCase())) {
      const linkClass = isDarkMode
        ? "text-blue-400 hover:text-blue-300 underline font-mono cursor-pointer"
        : "text-blue-600 hover:text-blue-800 underline font-mono cursor-pointer";

      return (
        <div className={`${lineClass} ${getLineClass(line)}`}>
          <span>&gt;&gt;&gt; </span>
          <button
            type="button"
            onClick={() => onHelpCommand(cmd.toUpperCase())}
            title={`Get help for ${cmd.toUpperCase()}`}
            className={linkClass}
          >
            {cmd}
          </button>
          <span>{rest}</span>
        </div>
      );
    }
  }

  const extraClass = isKlipperComment ? "italic opacity-70" : "";

  return (
    <div className={`${lineClass} ${getLineClass(line)} ${extraClass}`}>
      {text}
    </div>
  );
}

export function Terminal({ isDarkMode }) {
  const [input, setInput]           = useState("");
  const [isSending, setSend]        = useState(false);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [draft, setDraft]           = useState("");
  const [clearedCount, setClearedCount] = useState(0);

  // Search & Filter state
  const [filterPattern, setFilterPattern] = useState("");
  const [filterMode, setFilterMode]       = useState(loadFilterMode);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [showPresets, setShowPresets]     = useState(false);
  const [userPresets, setUserPresets]     = useState(loadUserPresets);

  // Autocomplete state
  const [suggestions, setSuggestions]               = useState([]);
  const [activeSuggestionIdx, setActiveSuggestionIdx] = useState(0);

  const liveCommands = useStore((s) => s.liveCommands);
  const clearLiveCommands = useStore((s) => s.clearLiveCommands);
  const simMode      = useStore((s) => s.simMode);
  const sendGcode    = useStore((s) => s.sendGcode);
  const isPrinting   = useStore((s) => s.telemetry?.state === "printing");
  const macros       = useStore((s) => s.macros);
  const uiTheme      = useStore((s) => s.theme);
  const consoleDirection    = useStore((s) => s.uiPrefs.consoleDirection);
  const consoleCompact      = useStore((s) => s.uiPrefs.consoleCompact);
  const hideTempsInConsole  = useStore((s) => s.uiPrefs.hideTempsInConsole);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const presetsMenuRef = useRef(null);

  useEffect(() => {
    if (liveCommands.length === 0) setClearedCount(0);
  }, [liveCommands.length]);

  // Click outside to close presets menu
  useEffect(() => {
    if (!showPresets) return;
    const handleClickOutside = (e) => {
      if (presetsMenuRef.current && !presetsMenuRef.current.contains(e.target)) {
        setShowPresets(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showPresets]);

  const handleClear = () => {
    setClearedCount(liveCommands.length);
    if (clearLiveCommands) clearLiveCommands();
  };

  const displayLines = useMemo(() => {
    const parseLive = (lines) => lines.map((l) => {
      const text = typeof l === "object" && l !== null ? (l.text ?? "") : String(l ?? "");
      const source = text.startsWith("!!") ? "error" :
                     text.startsWith("[QC]") || text.startsWith("[INDUS]") ? "indus" :
                     text.startsWith(">>> ") ? "user" : "device";
      return { text, source, highlight: true };
    });

    const activeLines = clearedCount > 0 ? liveCommands.slice(clearedCount) : liveCommands;
    return parseLive(activeLines);
  }, [liveCommands, clearedCount]);

  // Console filter: hide M105-style temperature status lines (e.g. "ok T:210.0 /210.0 B:60.0 /60.0")
  const tempFilteredLines = useMemo(() => {
    if (!hideTempsInConsole) return displayLines;
    const tempLine = /(^|\s)(B|T\d*):-?\d/;
    return displayLines.filter((l) => !tempLine.test(l.text || ""));
  }, [displayLines, hideTempsInConsole]);

  // Regex validity check
  const isRegexMode = filterMode === "regex";
  const regexValid = useMemo(() => {
    if (!isRegexMode || !filterPattern) return true;
    return isValidRegex(filterPattern);
  }, [isRegexMode, filterPattern]);

  // Search filter predicate
  const filterPredicate = useMemo(() => {
    return buildFilterPredicate(filterPattern, filterMode, caseSensitive);
  }, [filterPattern, filterMode, caseSensitive]);

  // Final filtered lines applying search filter on top
  const filteredLines = useMemo(() => {
    return applyFilter(tempFilteredLines, filterPredicate);
  }, [tempFilteredLines, filterPredicate]);

  // Candidates list for autocomplete & clickable help
  const completionCandidates = useMemo(() => {
    return buildCompletionList(COMMON_GCODES, macros);
  }, [macros]);

  const recognizedCommandsSet = useMemo(() => {
    return new Set(completionCandidates.map((c) => c.toUpperCase()));
  }, [completionCandidates]);

  const cycleFilterMode = () => {
    const modes = ["contains", "starts-with", "regex"];
    const nextIdx = (modes.indexOf(filterMode) + 1) % modes.length;
    const nextMode = modes[nextIdx];
    setFilterMode(nextMode);
    saveFilterMode(nextMode);
  };

  const applyPreset = (preset) => {
    setFilterPattern(preset.pattern);
    setFilterMode(preset.mode);
    setCaseSensitive(preset.caseSensitive);
    saveFilterMode(preset.mode);
    setShowPresets(false);
  };

  const saveCurrentAsPreset = () => {
    if (!filterPattern.trim()) return;
    const name = window.prompt("Preset name:", filterPattern.slice(0, 15));
    if (!name || !name.trim()) return;
    const updated = [
      ...userPresets,
      {
        name: name.trim(),
        pattern: filterPattern,
        mode: filterMode,
        caseSensitive,
      },
    ].slice(0, 5);
    setUserPresets(updated);
    saveUserPresets(updated);
    setShowPresets(false);
  };

  const deleteUserPreset = (idx, e) => {
    e.stopPropagation();
    const updated = userPresets.filter((_, i) => i !== idx);
    setUserPresets(updated);
    saveUserPresets(updated);
  };

  const getCmdHistory = () => {
    try {
      const saved = JSON.parse(localStorage.getItem("indus3d_cmd_history") || "[]");
      return Array.isArray(saved) ? saved : [];
    } catch {
      return [];
    }
  };

  const onHelpCommand = useCallback((cmd) => {
    sendGcode(`HELP ${cmd}`);
  }, [sendGcode]);

  const send = async (e) => {
    if (e) e.preventDefault();
    const cmd = input.trim();
    if (!cmd) return;
    setSuggestions([]);
    setSend(true);
    await sendGcode(cmd);
    setHistoryIdx(-1);
    setDraft("");
    setInput("");
    setSend(false);
  };

  const selectSuggestion = (chosen) => {
    setInput(chosen);
    setSuggestions([]);
  };

  const handleKeyDown = (e) => {
    // If autocomplete box is active
    if (suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveSuggestionIdx((prev) => (prev + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveSuggestionIdx((prev) => (prev - 1 + suggestions.length) % suggestions.length);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        selectSuggestion(suggestions[activeSuggestionIdx]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSuggestions([]);
        return;
      }
    }

    const hist = getCmdHistory();
    if (e.key === "ArrowUp") {
      if (!hist.length) return;
      e.preventDefault();
      if (historyIdx === -1) {
        setDraft(input);
        const nextIdx = hist.length - 1;
        setHistoryIdx(nextIdx);
        setInput(hist[nextIdx]);
      } else if (historyIdx > 0) {
        const nextIdx = historyIdx - 1;
        setHistoryIdx(nextIdx);
        setInput(hist[nextIdx]);
      }
    } else if (e.key === "ArrowDown") {
      if (historyIdx !== -1) {
        e.preventDefault();
        if (historyIdx < hist.length - 1) {
          const nextIdx = historyIdx + 1;
          setHistoryIdx(nextIdx);
          setInput(hist[nextIdx]);
        } else {
          setHistoryIdx(-1);
          setInput(draft);
        }
      }
    } else if (e.key === "Tab") {
      e.preventDefault();
      const current = input.trim();
      if (!current) return;
      const matches = getCompletions(current, completionCandidates);
      if (matches.length === 1) {
        setInput(matches[0]);
        setSuggestions([]);
      } else if (matches.length > 1) {
        setSuggestions(matches);
        setActiveSuggestionIdx(0);
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

  const consoleRef = React.useRef(null);
  React.useEffect(() => {
    if (consoleDirection === "bottom" && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [filteredLines, consoleDirection]);

  const termErrorClass = isDarkMode ? "text-red-400 font-bold" : "text-red-600 font-bold";

  const getLineClass = (l) => {
    if (l.active) return termActiveClass;
    if (l.source === "error" || (l.text && l.text.startsWith("!!"))) return termErrorClass;
    if (l.source === "user") return termUserClass;
    if (l.source === "indus") return termIndusClass;
    return "";
  };

  const lineClass = consoleCompact ? "whitespace-nowrap px-1 py-0" : "whitespace-nowrap px-1 py-0.5";
  const consoleBody = (
    <div
      ref={consoleRef}
      className={`flex-1 min-h-0 p-2 font-mono text-[10px] overflow-y-auto flex ${consoleDirection === "bottom" ? "flex-col" : "flex-col-reverse"} ${consoleCompact ? "gap-0" : ""} ${termBgClass}`}
    >
      {!filteredLines.length
        ? <div className="text-center italic opacity-40 self-center">
            {isPrinting || simMode ? "; Awaiting G-code..." : "; Console ready"}
          </div>
        : (consoleDirection === "bottom" ? filteredLines : [...filteredLines].reverse()).map((l, i) => (
            <ConsoleLineRenderer
              key={i}
              line={l}
              lineClass={lineClass}
              getLineClass={getLineClass}
              recognizedCommands={recognizedCommandsSet}
              onHelpCommand={onHelpCommand}
              isDarkMode={isDarkMode}
            />
          ))
      }
    </div>
  );

  const filterBorderClass = !regexValid
    ? "border-red-500 bg-red-950/20"
    : isDarkMode ? "border-gray-800 bg-gray-900/60" : "border-gray-300 bg-gray-50";

  const filterToolbar = (
    <div className="flex items-center gap-1.5 shrink-0 px-1 py-0.5 text-[10px] font-mono">
      <div className={`flex items-center flex-1 gap-1 px-2 py-0.5 rounded border transition-colors ${filterBorderClass}`}>
        <Search size={11} className="opacity-40 shrink-0" />
        <input
          type="text"
          value={filterPattern}
          onChange={(e) => setFilterPattern(e.target.value)}
          placeholder={`Filter logs (${filterMode})...`}
          className="bg-transparent flex-1 outline-none text-[10px] font-mono min-w-0"
        />
        {filterPattern && (
          <button
            type="button"
            onClick={() => setFilterPattern("")}
            className="opacity-50 hover:opacity-100 p-0.5"
            title="Clear filter"
          >
            <X size={10} />
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={cycleFilterMode}
        title={`Filter mode: ${filterMode} (click to cycle)`}
        className={`px-1.5 py-0.5 rounded border text-[9px] uppercase font-bold tracking-wider transition-colors ${
          isDarkMode
            ? "border-gray-700 bg-gray-800/80 text-gray-300 hover:bg-gray-700"
            : "border-gray-300 bg-gray-100 text-gray-700 hover:bg-gray-200"
        }`}
      >
        {filterMode === "contains" ? "sub" : filterMode === "starts-with" ? "start" : "regex"}
      </button>

      <button
        type="button"
        onClick={() => setCaseSensitive(!caseSensitive)}
        title={`Case sensitive: ${caseSensitive ? "ON" : "OFF"}`}
        className={`px-1.5 py-0.5 rounded border text-[9px] font-bold transition-colors ${
          caseSensitive
            ? "bg-blue-600/30 border-blue-500 text-blue-400"
            : isDarkMode
              ? "border-gray-700 bg-gray-800/40 text-gray-500 hover:text-gray-300"
              : "border-gray-300 bg-gray-100 text-gray-400 hover:text-gray-600"
        }`}
      >
        Aa
      </button>

      {/* Presets dropdown */}
      <div className="relative" ref={presetsMenuRef}>
        <button
          type="button"
          onClick={() => setShowPresets(!showPresets)}
          title="Filter Presets"
          className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[9px] transition-colors ${
            isDarkMode
              ? "border-gray-700 bg-gray-800/80 text-gray-300 hover:bg-gray-700"
              : "border-gray-300 bg-gray-100 text-gray-700 hover:bg-gray-200"
          }`}
        >
          <BookMarked size={10} />
          <ChevronDown size={8} />
        </button>

        {showPresets && (
          <div
            className={`absolute right-0 top-full mt-1 z-30 w-52 rounded-lg shadow-xl border p-1 font-mono text-[10px] ${
              isDarkMode
                ? "bg-gray-900 border-gray-700 text-gray-200"
                : "bg-white border-gray-300 text-gray-800"
            }`}
          >
            <div className="px-2 py-1 text-[8px] uppercase tracking-wider opacity-40 font-bold border-b border-gray-800">
              Built-in Presets
            </div>
            {BUILTIN_PRESETS.map((p) => (
              <button
                key={p.name}
                type="button"
                onClick={() => applyPreset(p)}
                className={`w-full text-left px-2 py-1 rounded flex items-center justify-between transition-colors ${
                  isDarkMode ? "hover:bg-gray-800" : "hover:bg-gray-100"
                }`}
              >
                <span>{p.name}</span>
                <span className="text-[8px] opacity-40 uppercase">{p.mode}</span>
              </button>
            ))}

            {userPresets.length > 0 && (
              <>
                <div className="px-2 py-1 mt-1 text-[8px] uppercase tracking-wider opacity-40 font-bold border-b border-t border-gray-800">
                  Custom Presets
                </div>
                {userPresets.map((p, idx) => (
                  <div
                    key={idx}
                    onClick={() => applyPreset(p)}
                    className={`px-2 py-1 rounded flex items-center justify-between cursor-pointer transition-colors ${
                      isDarkMode ? "hover:bg-gray-800" : "hover:bg-gray-100"
                    }`}
                  >
                    <span className="truncate flex-1">{p.name}</span>
                    <button
                      type="button"
                      onClick={(e) => deleteUserPreset(idx, e)}
                      title="Delete preset"
                      className="opacity-40 hover:opacity-100 hover:text-red-400 p-0.5 ml-1"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                ))}
              </>
            )}

            {filterPattern && (
              <div className="pt-1 mt-1 border-t border-gray-800">
                <button
                  type="button"
                  onClick={saveCurrentAsPreset}
                  className="w-full text-left px-2 py-1 rounded text-emerald-400 hover:bg-emerald-950/30 flex items-center gap-1 text-[9px] font-bold"
                >
                  + Save current filter
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {filterPattern && (
        <span className="text-[9px] opacity-50 shrink-0 tabular-nums">
          {filteredLines.length}/{tempFilteredLines.length}
        </span>
      )}
    </div>
  );

  const consoleForm = (
    <div className="relative shrink-0">
      {/* Autocomplete suggestions popup */}
      {suggestions.length > 0 && (
        <div
          className={`absolute left-0 bottom-full mb-1 w-64 max-h-40 overflow-y-auto rounded-lg shadow-2xl border z-20 font-mono text-[11px] ${
            isDarkMode
              ? "bg-gray-900 border-gray-700 text-gray-200"
              : "bg-white border-gray-300 text-gray-800"
          }`}
        >
          {suggestions.map((s, idx) => (
            <div
              key={s}
              onClick={() => selectSuggestion(s)}
              className={`px-3 py-1 cursor-pointer transition-colors ${
                idx === activeSuggestionIdx
                  ? "bg-blue-600 text-white font-bold"
                  : isDarkMode
                    ? "hover:bg-gray-800 text-gray-300"
                    : "hover:bg-gray-100 text-gray-700"
              }`}
            >
              {s}
            </div>
          ))}
        </div>
      )}

      <form onSubmit={send} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => {
             setInput(e.target.value);
             if (historyIdx === -1) setDraft(e.target.value);
             if (suggestions.length > 0) setSuggestions([]);
          }}
          onKeyDown={handleKeyDown}
          placeholder={simMode ? "e.g. G28 or TEST" : "e.g. G28, BED_MESH_CALIBRATE"}
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
    </div>
  );

  return (
    <div className={`h-full flex flex-col gap-2 ${consoleCompact ? "p-2" : "p-3"} ${t.panel}`}>
      <div className="flex items-center gap-2 shrink-0">
        <Activity size={15} className={brutalist ? "" : "text-emerald-500"} />
        <h3 className={t.heading}>Console</h3>
        {simMode && <span className={`text-[9px] px-2 py-0.5 ${t.chip} ${brutalist ? "bg-[#B7E4C7]" : "bg-blue-700 text-white"}`}>SIM</span>}
        <button
          type="button"
          onClick={handleClear}
          title="Clear console logs"
          className={`ml-auto flex items-center gap-1 text-[10px] px-2 py-0.5 rounded opacity-70 hover:opacity-100 transition-opacity ${
            brutalist ? "border border-[#111] bg-white text-[#111]" : "hover:bg-white/10 text-gray-400 hover:text-white"
          }`}
        >
          <Trash2 size={12} />
          <span>Clear</span>
        </button>
      </div>

      {filterToolbar}

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

// ── System Loads / Host Stats ───────────────────────────────────────────────
export function SystemStatsStrip({ isDarkMode }) {
  const systemStats = useStore((s) => s.systemStats);
  const fetchSystemStats = useStore((s) => s.fetchSystemStats);
  const brutalist = useIsBrutalist();

  useEffect(() => {
    fetchSystemStats();
    const interval = setInterval(() => {
      fetchSystemStats();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchSystemStats]);

  const cpuPct = Math.round(Number(systemStats?.cpu_percent ?? systemStats?.cpu_usage ?? systemStats?.cpu ?? 0));
  const ramPct = Math.round(Number(systemStats?.memory_percent ?? systemStats?.ram_percent ?? systemStats?.memory?.percent ?? systemStats?.ram_usage ?? 0));
  const cpuTemp = systemStats?.cpu_temp ?? systemStats?.temp ?? systemStats?.temperature;
  const osInfo = systemStats?.os_info ?? systemStats?.os ?? systemStats?.distribution ?? "NixOS";
  const arch = systemStats?.arch ?? systemStats?.architecture ?? "x86_64";

  return (
    <div className={`flex flex-wrap items-center gap-2 sm:gap-4 px-3 py-1.5 rounded-lg text-[11px] font-mono shrink-0 ${
      brutalist
        ? "bg-white border-2 border-[#111] text-[#111]"
        : isDarkMode
          ? "bg-gray-900/80 border border-gray-800 text-gray-300"
          : "bg-gray-100 border border-gray-200 text-gray-700"
    }`}>
      <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[10px] opacity-75">
        <Server size={13} className={brutalist ? "" : "text-blue-400"} />
        <span>Host:</span>
        <span className="text-emerald-500 font-bold">{osInfo}</span>
        <span className="opacity-60 text-[9px]">({arch})</span>
      </div>

      <div className="h-3 w-px bg-gray-500/30 hidden sm:block" />

      <div className="flex items-center gap-1.5">
        <Cpu size={12} className={brutalist ? "" : "text-amber-400"} />
        <span className="opacity-60">CPU:</span>
        <span className={`font-bold ${cpuPct > 80 ? "text-red-400" : cpuPct > 50 ? "text-amber-400" : "text-emerald-400"}`}>
          {cpuPct}%
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <HardDrive size={12} className={brutalist ? "" : "text-cyan-400"} />
        <span className="opacity-60">RAM:</span>
        <span className={`font-bold ${ramPct > 85 ? "text-red-400" : ramPct > 60 ? "text-amber-400" : "text-cyan-400"}`}>
          {ramPct}%
        </span>
      </div>

      {cpuTemp !== undefined && cpuTemp !== null && (
        <div className="flex items-center gap-1.5">
          <Thermometer size={12} className={brutalist ? "" : "text-rose-400"} />
          <span className="opacity-60">Temp:</span>
          <span className="font-bold text-rose-400">
            {Number(cpuTemp).toFixed(0)}°C
          </span>
        </div>
      )}
    </div>
  );
}

// ── Dashboard grid ────────────────────────────────────────────────────────────
const DEFAULT_LAYOUTS = {
  lg: [
    { i: "viewport", x: 0, y: 0, w: 8, h: 5 },
    { i: "status", x: 8, y: 0, w: 4, h: 2 },
    { i: "temperature", x: 8, y: 2, w: 4, h: 4 },
    { i: "quality", x: 0, y: 5, w: 3, h: 3 },
    { i: "toolhead", x: 3, y: 5, w: 5, h: 4 },
    { i: "cameras", x: 8, y: 5, w: 4, h: 3 },
    { i: "terminal", x: 0, y: 8, w: 6, h: 3 },
    { i: "macros", x: 6, y: 8, w: 6, h: 3 },
    { i: "actionlog", x: 0, y: 11, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 6, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 6, h: 4 },
  ],
  md: [
    { i: "viewport", x: 0, y: 0, w: 10, h: 5 },
    { i: "status", x: 0, y: 5, w: 5, h: 2 },
    { i: "quality", x: 5, y: 5, w: 5, h: 3 },
    { i: "temperature", x: 0, y: 7, w: 5, h: 4 },
    { i: "toolhead", x: 5, y: 8, w: 5, h: 4 },
    { i: "cameras", x: 0, y: 10, w: 5, h: 3 },
    { i: "terminal", x: 5, y: 11, w: 5, h: 3 },
    { i: "macros", x: 0, y: 13, w: 5, h: 3 },
    { i: "actionlog", x: 5, y: 14, w: 5, h: 3 },
    { i: "leds", x: 0, y: 999, w: 5, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 5, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 5, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 5, h: 4 },
  ],
  sm: [
    { i: "viewport", x: 0, y: 0, w: 6, h: 6 },
    { i: "status", x: 0, y: 8, w: 6, h: 2 },
    { i: "temperature", x: 0, y: 10, w: 6, h: 3 },
    { i: "quality", x: 0, y: 12, w: 6, h: 3 },
    { i: "toolhead", x: 0, y: 15, w: 6, h: 4 },
    { i: "cameras", x: 0, y: 18, w: 6, h: 3 },
    { i: "terminal", x: 0, y: 21, w: 6, h: 3 },
    { i: "macros", x: 0, y: 24, w: 6, h: 3 },
    { i: "actionlog", x: 0, y: 27, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 6, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 6, h: 4 },
  ],
};



const DEFAULT_STATIC_LAYOUTS = {
  lg: [
    { i: "viewport", x: 0, y: 0, w: 4, h: 5 },
    { i: "status", x: 4, y: 0, w: 4, h: 2 },
    { i: "toolhead", x: 8, y: 0, w: 4, h: 4 },
    { i: "temperature", x: 4, y: 2, w: 4, h: 4 },
    { i: "cameras", x: 8, y: 3, w: 4, h: 3 },
    { i: "terminal", x: 0, y: 5, w: 6, h: 4 },
    { i: "macros", x: 6, y: 5, w: 6, h: 4 },
    { i: "actionlog", x: 0, y: 9, w: 12, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 6, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 6, h: 4 },
  ],
  md: [
    { i: "viewport", x: 0, y: 0, w: 5, h: 5 },
    { i: "status", x: 5, y: 0, w: 5, h: 2 },
    { i: "toolhead", x: 5, y: 2, w: 5, h: 4 },
    { i: "temperature", x: 0, y: 5, w: 5, h: 4 },
    { i: "cameras", x: 5, y: 5, w: 5, h: 3 },
    { i: "terminal", x: 0, y: 8, w: 5, h: 4 },
    { i: "macros", x: 5, y: 8, w: 5, h: 4 },
    { i: "actionlog", x: 0, y: 12, w: 10, h: 3 },
    { i: "leds", x: 0, y: 999, w: 5, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 5, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 5, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 5, h: 4 },
  ],
  sm: [
    { i: "viewport", x: 0, y: 0, w: 6, h: 4 },
    { i: "status", x: 0, y: 4, w: 6, h: 2 },
    { i: "temperature", x: 0, y: 6, w: 6, h: 4 },
    { i: "toolhead", x: 0, y: 9, w: 6, h: 4 },
    { i: "cameras", x: 0, y: 12, w: 6, h: 3 },
    { i: "terminal", x: 0, y: 15, w: 6, h: 4 },
    { i: "macros", x: 0, y: 19, w: 6, h: 4 },
    { i: "actionlog", x: 0, y: 23, w: 6, h: 3 },
    { i: "leds", x: 0, y: 999, w: 6, h: 3 },
    { i: "vibration", x: 0, y: 1000, w: 6, h: 3 },
    { i: "sensors", x: 0, y: 1001, w: 6, h: 3 },
    { i: "queue", x: 0, y: 1002, w: 6, h: 4 },
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
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2 shrink-0">
          <SystemStatsStrip isDarkMode={isDarkMode} />
          <div className="flex items-center gap-2 ml-auto">
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
            <div key="sensors"><CardWrapper isLocked={isLocked}><MoonrakerSensorsCard /></CardWrapper></div>
            <div key="queue"><CardWrapper isLocked={isLocked}><QueueCard /></CardWrapper></div>
          </ResponsiveGridLayout>
        </div>
      </div>
  );
}
