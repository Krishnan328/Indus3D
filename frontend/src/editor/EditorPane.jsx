import React, { useEffect, useMemo, useRef, useState } from "react";
import { ListTree, ChevronsDownUp, ChevronsUpDown, Search as SearchIcon, Keyboard, WrapText } from "lucide-react";
import { Compartment, EditorState } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, highlightSpecialChars, drawSelection,
  dropCursor, rectangularSelection, crosshairCursor,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { foldGutter, foldKeymap, foldAll, unfoldAll, indentOnInput, bracketMatching } from "@codemirror/language";
import { search, searchKeymap, highlightSelectionMatches, openSearchPanel, searchPanelOpen } from "@codemirror/search";
import { useStore } from "../store";
import { languageFor, themeExtensions } from "./cmLanguages";
import { outlineOf, SHORTCUTS } from "./syntax";
import { Modal } from "../files/ui";

// The CodeMirror 6 editor body. Loaded lazily (dynamic import) so CodeMirror stays out of the main bundle.
// The host owns saving: Mod-S calls ``onSave``, Mod-Shift-S calls ``onSaveRestart``. ``value`` is the initial
// text (key the component by file); ``onChange`` reports every edit.
const compartments = () => ({ lang: new Compartment(), theme: new Compartment(), ro: new Compartment(), wrap: new Compartment() });

function Help({ onClose }) {
  return (
    <Modal title="Editor keyboard shortcuts" onClose={onClose} labelledBy="editor-help-title">
      <table className="w-full text-xs">
        <tbody>
          {SHORTCUTS.map(([k, d]) => (
            <tr key={k} className="border-b border-white/10"><td className="py-1.5 pr-4 font-mono whitespace-nowrap">{k}</td><td className="py-1.5 opacity-80">{d}</td></tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}

function Outline({ items, onJump, onClose }) {
  const [q, setQ] = useState("");
  const shown = items.filter((i) => i.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="absolute right-2 top-10 z-20 w-72 max-h-72 flex flex-col text-xs bg-gray-900 text-gray-100 border border-gray-700 rounded-lg shadow-xl">
      <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Jump to…" aria-label="Filter outline"
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } if (e.key === "Enter" && shown[0]) onJump(shown[0]); }}
        className="m-2 px-2 py-1 bg-black/30 border border-white/10 rounded outline-none" />
      <ul className="overflow-auto pb-1" role="listbox" aria-label="Sections">
        {shown.length === 0 && <li className="px-3 py-2 opacity-50 italic">Nothing to jump to in this file.</li>}
        {shown.map((i) => (
          <li key={`${i.line}`}>
            <button type="button" onClick={() => onJump(i)} className="w-full text-left px-3 py-1 hover:bg-white/10 flex gap-2" style={{ paddingLeft: 12 + i.depth * 12 }}>
              <span className={`truncate font-mono ${i.kind === "auto" || i.kind === "autosave" ? "opacity-60" : ""}`}>{i.name}</span>
              <span className="ml-auto opacity-40">{i.line + 1}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function EditorPane({ value, onChange, mode = "text", readOnly = false, onSave, onSaveRestart, onEscape, className = "" }) {
  const themeName = useStore((s) => s.theme);
  const isDark = useStore((s) => s.isDarkMode);
  const tabSize = useStore((s) => s.uiPrefs?.editorTabSize) || 2;
  const hostRef = useRef(null);
  const viewRef = useRef(null);
  const cmp = useRef(compartments());
  const cb = useRef({});
  const [doc, setDoc] = useState(value);
  const [panel, setPanel] = useState(null);                 // "outline" | "help" | null
  const [wrap, setWrap] = useState(mode === "markdown");

  useEffect(() => { cb.current = { onChange, onSave, onSaveRestart, onEscape, panel }; });

  useEffect(() => {
    const c = cmp.current;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(), history(), foldGutter(), drawSelection(), dropCursor(),
        EditorState.allowMultipleSelections.of(true), indentOnInput(), bracketMatching(), rectangularSelection(), crosshairCursor(),
        highlightActiveLine(), highlightSelectionMatches(), search({ top: true }),
        EditorState.tabSize.of(tabSize),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { cb.current.onSave?.(); return true; } },
          { key: "Mod-Shift-s", preventDefault: true, run: () => { cb.current.onSaveRestart?.(); return true; } },
          { key: "Mod-Alt-o", preventDefault: true, run: () => { setPanel("outline"); return true; } },
          { key: "F1", preventDefault: true, run: () => { setPanel("help"); return true; } },
          { key: "Escape", run: (v) => {
            if (searchPanelOpen(v.state)) return false;                    // let the search panel close itself first
            if (cb.current.panel) { setPanel(null); return true; }
            if (cb.current.onEscape) { cb.current.onEscape(); return true; }
            return false;
          } },
          ...foldKeymap, ...searchKeymap, ...historyKeymap, indentWithTab, ...defaultKeymap,
        ]),
        c.lang.of(languageFor(mode)), c.theme.of(themeExtensions(themeName, isDark)),
        c.ro.of([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
        c.wrap.of(wrap ? EditorView.lineWrapping : []),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) { const text = u.state.doc.toString(); cb.current.onChange?.(text); setDoc(text); }
        }),
      ],
    });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => { view.destroy(); viewRef.current = null; };
    // The view is created once per mounted file; later prop changes are applied through the compartments below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { viewRef.current?.dispatch({ effects: cmp.current.theme.reconfigure(themeExtensions(themeName, isDark)) }); }, [themeName, isDark]);
  useEffect(() => { viewRef.current?.dispatch({ effects: cmp.current.lang.reconfigure(languageFor(mode)) }); }, [mode]);
  useEffect(() => {
    viewRef.current?.dispatch({ effects: cmp.current.ro.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]) });
  }, [readOnly]);
  useEffect(() => { viewRef.current?.dispatch({ effects: cmp.current.wrap.reconfigure(wrap ? EditorView.lineWrapping : []) }); }, [wrap]);

  const outline = useMemo(() => (panel === "outline" ? outlineOf(doc, mode) : []), [panel, doc, mode]);
  const canOutline = mode === "klipper" || mode === "moonraker" || mode === "markdown";

  const jump = (item) => {
    const view = viewRef.current;
    if (!view) return;
    const pos = view.state.doc.line(item.line + 1).from;
    view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: "start", yMargin: 8 }) });
    view.focus();
    setPanel(null);
  };

  const tool = "px-2 py-1 text-[11px] inline-flex items-center gap-1 rounded hover:bg-white/10 disabled:opacity-30";
  return (
    <div className={`relative flex flex-col min-h-0 h-full ${className}`}>
      <div className="flex items-center gap-1 px-2 py-1 border-b border-white/10 text-gray-300 shrink-0 flex-wrap">
        <button type="button" className={tool} disabled={!canOutline} onClick={() => setPanel(panel === "outline" ? null : "outline")} title="Outline (Ctrl/Cmd+Alt+O)"><ListTree size={13} /> Outline</button>
        <button type="button" className={tool} onClick={() => viewRef.current && foldAll(viewRef.current)} title="Fold all (Ctrl+Alt+[)"><ChevronsDownUp size={13} /> Fold all</button>
        <button type="button" className={tool} onClick={() => viewRef.current && unfoldAll(viewRef.current)} title="Unfold all (Ctrl+Alt+])"><ChevronsUpDown size={13} /> Unfold all</button>
        <button type="button" className={tool} onClick={() => viewRef.current && openSearchPanel(viewRef.current)} title="Find (Ctrl/Cmd+F)"><SearchIcon size={13} /> Find</button>
        <button type="button" className={tool} aria-pressed={wrap} onClick={() => setWrap(!wrap)} title="Wrap long lines"><WrapText size={13} /> Wrap</button>
        <span className="ml-auto text-[10px] uppercase tracking-widest opacity-50">{readOnly ? "read-only · " : ""}{mode}</span>
        <button type="button" className={tool} onClick={() => setPanel("help")} title="Keyboard shortcuts (F1)" aria-label="Keyboard shortcuts"><Keyboard size={13} /></button>
      </div>
      <div ref={hostRef} className="flex-1 min-h-0 overflow-hidden" />
      {panel === "outline" && <Outline items={outline} onJump={jump} onClose={() => setPanel(null)} />}
      {panel === "help" && <Help onClose={() => setPanel(null)} />}
    </div>
  );
}
