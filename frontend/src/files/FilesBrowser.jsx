import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Play, ListPlus, Flame, RefreshCw, Pencil, Copy, Scissors, ClipboardPaste, Download, Trash2, FolderPlus, FileArchive, Eye, FileEdit, X } from "lucide-react";
import { API, useStore } from "../store";
import { fileUrl } from "../slices/filesSlice";
import {
  joinPath, parentPath, applyFilters, sortEntries, matchesSearch, pickThumbnail, fileKind, canPrint as isPrintable,
  isEditable, isWithin,
} from "./filesLogic";
import { loadFmPrefs, saveFmPrefs } from "./prefs";
import { GCODE_COLUMNS, PLAIN_COLUMNS, visibleColumns } from "./columns";
import { ListHeader, ListRow, ParentRow, GridCard } from "./FileRows";
import { Toolbar, RootTabs, Breadcrumbs, DiskBar } from "./FilesToolbar";
import { ContextMenu } from "./ContextMenu";
import { UploadTray } from "./UploadTray";
import { QuickFinder } from "./QuickFinder";
import { FilePreview } from "./FilePreview";
import { NameDialog, ConfirmDialog, NameList, WarnLine, QueueAddDialog } from "./FileDialogs";
import { Btn, Toast } from "./ui";
import { useUi } from "./useUi";

const EditorModal = React.lazy(() => import("../editor/EditorModal"));
const INTERNAL = "application/x-indus3d-files";

function useWidth(ref) {
  const [w, setW] = useState(1000);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver((entries) => setW(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
const hasInternal = (e) => Array.from(e.dataTransfer?.types || []).includes(INTERNAL);

// The Files tab: browse a Moonraker root, sort and filter, select several files, drag and drop, upload with
// progress, preview, edit and queue. All server calls go through filesSlice.
export function FilesBrowser({ onOpenQueue }) {
  const u = useUi();
  const fm = useStore((s) => s.fm);
  const thumbs = useStore((s) => s.fmThumbs);
  const dateFormat = useStore((s) => s.uiPrefs?.dateFormat);
  const fmLoadRoots = useStore((s) => s.fmLoadRoots);
  const fmOpen = useStore((s) => s.fmOpen);
  const fmRefresh = useStore((s) => s.fmRefresh);
  const fmDelete = useStore((s) => s.fmDelete);
  const fmMkdir = useStore((s) => s.fmMkdir);
  const fmRename = useStore((s) => s.fmRename);
  const fmTransfer = useStore((s) => s.fmTransfer);
  const fmThumbsFor = useStore((s) => s.fmThumbsFor);
  const fmUpload = useStore((s) => s.fmUpload);
  const fmDownloadZip = useStore((s) => s.fmDownloadZip);
  const fmRefreshMeta = useStore((s) => s.fmRefreshMeta);
  const queueAdd = useStore((s) => s.queueAdd);
  const startPrintFile = useStore((s) => s.startPrintFile);
  const setHeaterTarget = useStore((s) => s.setHeaterTarget);

  const [prefs, setPrefs] = useState(loadFmPrefs);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [anchor, setAnchor] = useState(null);
  const [menu, setMenu] = useState(null);
  const [clip, setClip] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [preview, setPreview] = useState(null);
  const [editing, setEditing] = useState(null);
  const [finder, setFinder] = useState(false);
  const [drop, setDrop] = useState(null);                 // {kind: "row"|"crumb"|"root"|"here", key}
  const [toast, setToast] = useState(null);
  const listRef = useRef(null);
  const fileInput = useRef(null);
  const searchRef = useRef(null);
  const width = useWidth(listRef);

  const root = fm.root;
  const path = fm.path;
  const rootInfo = fm.roots.find((r) => r.name === root);
  const canWrite = fm.writable && (rootInfo?.writable ?? true);
  const isGcodeRoot = root === "gcodes";
  const printBusy = fm.print?.busy;
  const note = useCallback((message, ok = true, action = null) => setToast({ message, ok, action, ms: ok ? 4500 : 7000 }), []);
  const closeToast = useCallback(() => setToast(null), []);

  const setPref = (patch) => setPrefs((p) => { const n = { ...p, ...patch }; saveFmPrefs(n); return n; });

  // ── Loading ──────────────────────────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    fmLoadRoots().then(() => fmOpen(useStore.getState().fm.root, useStore.getState().fm.path));
  }, [fmLoadRoots, fmOpen]);

  const go = useCallback((r, p = "") => { setSelected(new Set()); setAnchor(null); setSearch(""); fmOpen(r, p); }, [fmOpen]);

  const rows = useMemo(() => {
    let list = applyFilters(fm.entries, prefs.filters);
    if (search.trim()) list = list.filter((e) => matchesSearch(e.name, search));
    return sortEntries(list, prefs.sort.key, prefs.sort.dir);
  }, [fm.entries, prefs.filters, prefs.sort, search]);

  const cols = useMemo(() => visibleColumns(isGcodeRoot ? GCODE_COLUMNS : PLAIN_COLUMNS, width), [isGcodeRoot, width]);
  const showThumbs = isGcodeRoot;
  const thumbOf = useCallback((e) => (e.meta?.thumbnails ? pickThumbnail(e.meta.thumbnails, prefs.thumb) : null), [prefs.thumb]);

  // Thumbnails for what is shown: one batched request per 30 files, cached in the store.
  useEffect(() => {
    if (!showThumbs || !rows.length) return;
    const want = rows.filter((e) => e.type === "file").map((e) => thumbOf(e)?.path && ({ root, path: thumbOf(e).path, v: e.modified })).filter(Boolean);
    if (want.length) fmThumbsFor(want);
  }, [rows, showThumbs, root, thumbOf, fmThumbsFor]);

  const thumbSrc = (e) => { const t = thumbOf(e); return t ? thumbs[`${root}:${t.path}`] : null; };
  const byPath = useMemo(() => new Map(fm.entries.map((e) => [e.path, e])), [fm.entries]);
  const selectedEntries = useMemo(() => [...selected].map((p) => byPath.get(p)).filter(Boolean), [selected, byPath]);
  const isActiveFile = (e) => root === "gcodes" && printBusy && fm.print.filename === e.path;

  // ── Selection ────────────────────────────────────────────────────────────────────────────────────────────
  const onRowClick = (ev, entry) => {
    if (ev.shiftKey && anchor) {
      const a = rows.findIndex((r) => r.path === anchor);
      const b = rows.findIndex((r) => r.path === entry.path);
      if (a >= 0 && b >= 0) { setSelected(new Set(rows.slice(Math.min(a, b), Math.max(a, b) + 1).map((r) => r.path))); return; }
    }
    if (ev.ctrlKey || ev.metaKey) {
      setSelected((s) => { const n = new Set(s); if (n.has(entry.path)) n.delete(entry.path); else n.add(entry.path); return n; });
    } else {
      setSelected(new Set([entry.path]));
    }
    setAnchor(entry.path);
  };
  const onToggle = (entry) => { setSelected((s) => { const n = new Set(s); if (n.has(entry.path)) n.delete(entry.path); else n.add(entry.path); return n; }); setAnchor(entry.path); };

  // ── Actions ──────────────────────────────────────────────────────────────────────────────────────────────
  const result = (r, okMsg) => { if (r.ok) { if (okMsg) note(okMsg); } else note(r.message, false); return r; };

  const doPrint = (entry) => setDialog({ type: "print", entry });
  const confirmPrint = async (entry) => {
    const r = await startPrintFile(entry.path);
    setDialog(null);
    setPreview(null);
    if (r?.error) note(r.error, false); else note(`Started ${entry.name}`);
  };

  const doPreheat = async (entry) => {
    const m = entry.meta || {};
    if (!setHeaterTarget) { note("Heater controls are not available in this build", false); return; }
    const jobs = [];
    if (m.first_layer_bed_temp != null) jobs.push(setHeaterTarget("heater_bed", m.first_layer_bed_temp));
    if (m.first_layer_extr_temp != null) jobs.push(setHeaterTarget("extruder", m.first_layer_extr_temp));
    const rs = await Promise.all(jobs);
    const bad = rs.find((r) => !r.ok);
    if (bad) note(bad.message, false); else note(`Preheating for ${entry.name}: nozzle ${m.first_layer_extr_temp ?? "–"}°C, bed ${m.first_layer_bed_temp ?? "–"}°C`);
  };
  const canPreheat = (e) => !printBusy && e.meta && (e.meta.first_layer_extr_temp != null || e.meta.first_layer_bed_temp != null);

  const doQueue = (entries) => setDialog({ type: "queue", names: entries.filter((e) => e.type === "file" && isPrintable(e.name)).map((e) => e.path) });
  const submitQueue = async (names, opts) => {
    const r = await queueAdd(names, opts);
    setDialog(null);
    if (r.ok) note(`Added ${r.body.added} job${r.body.added > 1 ? "s" : ""} to the queue`, true, { label: "Open queue", run: () => { closeToast(); onOpenQueue?.(); } });
    else if (r.body?.setup) { note("The print queue is not enabled in Moonraker", false, { label: "How to enable", run: () => { closeToast(); onOpenQueue?.(); } }); }
    else note(r.message, false);
  };

  const doRefreshMeta = async (entry) => result(await fmRefreshMeta(entry.path), "Metadata refreshed");
  const doDownload = (entry) => {
    const a = document.createElement("a");
    a.href = fileUrl(API, root, entry.path);
    a.download = entry.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  const doZip = async (entries) => result(await fmDownloadZip(root, entries.map((e) => e.path)), null);

  const doRename = (entry) => setDialog({ type: "rename", entry });
  const submitRename = async (entry, name) => {
    const r = await fmRename(root, entry.path, name);
    if (r.ok) { setDialog(null); setSelected(new Set()); return null; }
    return r.message;
  };
  const doMkdir = () => setDialog({ type: "mkdir" });
  const submitMkdir = async (name) => {
    const r = await fmMkdir(root, joinPath(path, name));
    if (r.ok) { setDialog(null); return null; }
    return r.message;
  };

  const doDelete = (entries) => setDialog({ type: "delete", entries });
  const confirmDelete = async (entries, confirmed = false) => {
    const r = await fmDelete(root, entries.map((e) => e.path), confirmed);
    if (!r.ok && r.body?.code === "confirmation_required") {
      setDialog({ type: "delete-nonempty", entries, folders: r.body.needs_confirmation });
      return;
    }
    setDialog(null);
    setSelected(new Set());
    if (!r.ok) { note(r.message, false); return; }
    const failed = (r.body.results || []).filter((x) => !x.ok);
    if (failed.length) note(`${failed.length} item(s) could not be deleted: ${failed[0].error}`, false);
    else note(`Deleted ${entries.length} item${entries.length > 1 ? "s" : ""}`);
  };

  const doEdit = (entry) => { setPreview(null); setEditing(entry); };

  const transfer = async (kind, items, destDir, destRoot, overwrite = false) => {
    const r = await fmTransfer(kind, destRoot ? clip?.root || root : root, items, destDir, { destRoot, overwrite });
    if (!r.ok && r.body?.code === "exists") { setDialog({ type: "overwrite", kind, items, destDir, destRoot, conflicts: r.body.conflicts }); return r; }
    setDialog(null);
    if (r.ok) { note(`${kind === "move" ? "Moved" : "Copied"} ${items.length} item${items.length > 1 ? "s" : ""}`); if (kind === "move") setSelected(new Set()); }
    else note(r.message, false);
    return r;
  };

  const paste = (destDir = path) => {
    if (!clip) return;
    if (clip.root === root && clip.mode === "copy" && destDir === parentPath(clip.items[0] ?? "")) { note("Choose another folder to paste the copy into", false); return; }
    transfer(clip.mode === "cut" ? "move" : "copy", clip.items, destDir, root).then((r) => { if (r?.ok && clip.mode === "cut") setClip(null); });
  };

  // ── Drag and drop ────────────────────────────────────────────────────────────────────────────────────────
  const uploadDropped = (e, destDir) => {
    const files = Array.from(e.dataTransfer.files || []);
    const items = Array.from(e.dataTransfer.items || []);
    const dirs = items.filter((it) => it.webkitGetAsEntry?.()?.isDirectory).length;
    if (dirs) note("Folders can not be uploaded directly: zip the folder or drop its files", false);
    const plain = files.filter((f, i) => !(items[i]?.webkitGetAsEntry?.()?.isDirectory));
    if (plain.length && canWrite) fmUpload(root, destDir, plain);
    else if (plain.length) note(`${root} is read-only`, false);
  };

  const dropHandlerFor = (destDir, destRoot = root) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDrop(null);
    if (hasInternal(e)) {
      let payload;
      try { payload = JSON.parse(e.dataTransfer.getData(INTERNAL)); } catch { return; }
      const items = (payload.items || []).filter((p) => !(payload.root === destRoot && isWithin(destDir, p)));
      if (!items.length || (payload.root === destRoot && items.every((p) => parentPath(p) === destDir))) return;
      const copy = e.ctrlKey || e.altKey;
      fmTransfer(copy ? "copy" : "move", payload.root, items, destDir, { destRoot }).then((r) => {
        if (!r.ok && r.body?.code === "exists") setDialog({ type: "overwrite", kind: copy ? "copy" : "move", items, destDir, destRoot, srcRoot: payload.root, conflicts: r.body.conflicts });
        else if (!r.ok) note(r.message, false);
        else note(`${copy ? "Copied" : "Moved"} ${items.length} item${items.length > 1 ? "s" : ""}`);
      });
    } else if (hasFiles(e)) {
      uploadDropped(e, destDir);
    }
  };

  const dragOverFor = (kind, key, writable = true) => (e) => {
    if (!(hasInternal(e) || hasFiles(e))) return;
    if (!writable) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = hasInternal(e) && (e.ctrlKey || e.altKey) ? "copy" : (hasFiles(e) ? "copy" : "move");
    setDrop((d) => (d && d.kind === kind && d.key === key ? d : { kind, key }));
  };
  const dragLeave = () => setDrop(null);

  const rowHandlers = {
    onClick: onRowClick, onToggle,
    onOpen: (entry) => open(entry),
    onContext: (e, entry) => {
      e.preventDefault();
      if (!selected.has(entry.path)) { setSelected(new Set([entry.path])); setAnchor(entry.path); }
      setMenu({ x: e.clientX, y: e.clientY, target: entry });
    },
    onDragStart: (e, entry) => {
      const items = selected.has(entry.path) ? [...selected] : [entry.path];
      if (!selected.has(entry.path)) setSelected(new Set([entry.path]));
      e.dataTransfer.setData(INTERNAL, JSON.stringify({ root, items }));
      e.dataTransfer.effectAllowed = "copyMove";
    },
    onDragOver: (e, entry) => (entry.type === "dir" ? dragOverFor("row", entry.path, canWrite)(e) : undefined),
    onDragLeave: dragLeave,
    onDrop: (e, entry) => { if (entry.type === "dir") dropHandlerFor(entry.path)(e); },
  };

  function open(entry) {
    if (entry.type === "dir") { go(root, entry.path); return; }
    const kind = fileKind(entry.name);
    if ((kind === "text") && isEditable(entry.name) && rootInfo) setEditing(entry);
    else setPreview(entry);
  }

  // ── Keyboard ─────────────────────────────────────────────────────────────────────────────────────────────
  const selNames = selectedEntries;
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p" && !dialog && !editing) { e.preventDefault(); setFinder(true); return; }
      if (typing || dialog || editing || preview || finder) return;
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "Escape") setSelected(new Set());
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); setSelected(new Set(rows.map((r) => r.path))); }
      else if (e.key === "Delete" && selNames.length && canWrite) doDelete(selNames);
      else if (e.key === "F2" && selNames.length === 1 && canWrite) doRename(selNames[0]);
      else if (e.key === "Enter" && selNames.length === 1) open(selNames[0]);
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && selNames.length) setClip({ mode: "copy", root, items: selNames.map((x) => x.path) });
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x" && selNames.length && canWrite) setClip({ mode: "cut", root, items: selNames.map((x) => x.path) });
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v" && clip && canWrite) paste();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── Context menu ─────────────────────────────────────────────────────────────────────────────────────────
  const menuItems = () => {
    const target = menu.target;
    const sel = selectedEntries.length > 1 && selected.has(target?.path) ? selectedEntries : (target ? [target] : []);
    const single = sel.length === 1 ? sel[0] : null;
    const gcodes = sel.filter((e) => e.type === "file" && isPrintable(e.name));
    const items = [];
    if (single && single.type === "dir") items.push({ label: "Open", icon: <Eye size={13} />, onClick: () => go(root, single.path) });
    if (single && single.type === "file") {
      if (isPrintable(single.name)) items.push({ label: "Print", icon: <Play size={13} />, disabled: printBusy, hint: printBusy ? "A print is already running" : "", onClick: () => doPrint(single) });
    }
    if (gcodes.length) items.push({ label: gcodes.length > 1 ? `Add ${gcodes.length} to queue` : "Add to queue", icon: <ListPlus size={13} />, onClick: () => doQueue(gcodes) });
    if (single && single.type === "file" && isPrintable(single.name)) {
      items.push({ label: "Preheat", icon: <Flame size={13} />, disabled: !canPreheat(single), hint: canPreheat(single) ? `Nozzle ${single.meta.first_layer_extr_temp ?? "–"}°C, bed ${single.meta.first_layer_bed_temp ?? "–"}°C` : "No temperatures in the metadata, or a print is running", onClick: () => doPreheat(single) });
      items.push({ label: "Refresh metadata", icon: <RefreshCw size={13} />, onClick: () => doRefreshMeta(single) });
    }
    if (single && single.type === "file") {
      items.push({ label: "Preview", icon: <Eye size={13} />, onClick: () => setPreview(single) });
      if (isEditable(single.name)) items.push({ label: canWrite ? "Edit" : "View in editor", icon: <FileEdit size={13} />, onClick: () => doEdit(single) });
    }
    if (items.length) items.push({ separator: true });
    if (sel.length) {
      if (single) items.push({ label: "Rename", icon: <Pencil size={13} />, shortcut: "F2", disabled: !canWrite, onClick: () => doRename(single) });
      items.push({ label: "Copy", icon: <Copy size={13} />, shortcut: "Ctrl+C", onClick: () => setClip({ mode: "copy", root, items: sel.map((x) => x.path) }) });
      items.push({ label: "Move (cut)", icon: <Scissors size={13} />, shortcut: "Ctrl+X", disabled: !canWrite, onClick: () => setClip({ mode: "cut", root, items: sel.map((x) => x.path) }) });
    }
    if (clip) {
      const into = single?.type === "dir" ? single.path : path;
      items.push({ label: `Paste ${clip.items.length} here${single?.type === "dir" ? ` (${single.name})` : ""}`, icon: <ClipboardPaste size={13} />, shortcut: "Ctrl+V", disabled: !canWrite, onClick: () => paste(into) });
    }
    if (sel.length) {
      if (single && single.type === "file") items.push({ label: "Download", icon: <Download size={13} />, onClick: () => doDownload(single) });
      items.push({ label: sel.length > 1 || single?.type === "dir" ? "Download as ZIP" : "Download as ZIP", icon: <FileArchive size={13} />, onClick: () => doZip(sel) });
      items.push({ separator: true });
      items.push({ label: sel.length > 1 ? `Delete ${sel.length} items` : "Delete", icon: <Trash2 size={13} />, shortcut: "Del", danger: true, disabled: !canWrite, onClick: () => doDelete(sel) });
    } else {
      items.push({ label: "New folder", icon: <FolderPlus size={13} />, disabled: !canWrite, onClick: doMkdir });
    }
    return items;
  };

  // ── Render ───────────────────────────────────────────────────────────────────────────────────────────────
  const total = fm.entries.length;
  const hiddenCount = total - applyFilters(fm.entries, prefs.filters).length;
  const handlersHere = { dropOver: dragOverFor("here", "here", canWrite), drop: dropHandlerFor(path) };

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-2">
      <div className={`flex flex-col gap-2 px-3 py-2 ${u.t.panel}`}>
        <div className="flex items-center gap-3 flex-wrap">
          <RootTabs roots={fm.roots} active={root} dropRoot={drop?.kind === "root" ? drop.key : null} onPick={(r) => go(r, "")}
            onDragOverRoot={(e, r) => dragOverFor("root", r.name, r.writable)(e)} onDragLeaveRoot={dragLeave}
            onDropRoot={(e, r) => dropHandlerFor("", r.name)(e)} />
          <div className="ml-auto"><DiskBar usage={fm.diskUsage} /></div>
        </div>
        <Breadcrumbs root={root} path={path} dropPath={drop?.kind === "crumb" ? drop.key : null} onGo={(p) => go(root, p)}
          onDragOverCrumb={(e, p) => dragOverFor("crumb", p, canWrite)(e)} onDragLeaveCrumb={dragLeave} onDropCrumb={(e, p) => dropHandlerFor(p)(e)} />
        <Toolbar search={search} onSearch={setSearch} searchRef={searchRef} view={prefs.view} onView={(v) => setPref({ view: v })}
          thumb={prefs.thumb} onThumb={(n) => setPref({ thumb: n })} filters={prefs.filters} onFilters={(f) => setPref({ filters: f })}
          canWrite={canWrite} loading={fm.loading} onMkdir={doMkdir} onUpload={() => fileInput.current?.click()} onRefresh={fmRefresh}
          onFinder={() => setFinder(true)} hasMeta={isGcodeRoot && prefs.view === "list"} />
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) fmUpload(root, path, e.target.files); e.target.value = ""; }} />
      </div>

      {fm.diskUsage?.percent >= 85 && (
        <div role="alert" className={`px-3 py-2 text-xs ${fm.diskUsage.percent >= 95 ? "bg-red-900/60 text-red-100" : "bg-amber-900/50 text-amber-100"} ${u.brutalist ? "border-2 border-[#111] !text-[#111] !bg-[#FFE9A8]" : "rounded"}`}>
          The printer's storage is {fm.diskUsage.percent}% full. Delete old G-code, timelapse or log files before uploading more.
        </div>
      )}
      {fm.print?.busy && root === "config" && (
        <div role="note" className="px-3 py-2 text-xs bg-sky-900/40 text-sky-100 rounded">A print is running: files in config can be read but not changed.</div>
      )}

      {selectedEntries.length > 0 && (
        <div className={`flex items-center gap-2 flex-wrap px-3 py-1.5 text-xs ${u.t.panel}`} role="toolbar" aria-label="Selection actions">
          <span className="font-bold">{selectedEntries.length} selected</span>
          {selectedEntries.some((e) => e.type === "file" && isPrintable(e.name)) && <Btn onClick={() => doQueue(selectedEntries)}><ListPlus size={12} /> Add to queue</Btn>}
          <Btn onClick={() => doZip(selectedEntries)}><FileArchive size={12} /> ZIP</Btn>
          <Btn onClick={() => setClip({ mode: "copy", root, items: selectedEntries.map((x) => x.path) })}><Copy size={12} /> Copy</Btn>
          <Btn disabled={!canWrite} onClick={() => setClip({ mode: "cut", root, items: selectedEntries.map((x) => x.path) })}><Scissors size={12} /> Move</Btn>
          <Btn kind="danger" disabled={!canWrite} onClick={() => doDelete(selectedEntries)}><Trash2 size={12} /> Delete</Btn>
          <Btn onClick={() => setSelected(new Set())} className="ml-auto"><X size={12} /> Clear</Btn>
        </div>
      )}
      {clip && (
        <div className={`flex items-center gap-2 px-3 py-1.5 text-xs ${u.t.panel}`}>
          <span>{clip.items.length} item{clip.items.length > 1 ? "s" : ""} from <b>{clip.root}</b> to {clip.mode === "cut" ? "move" : "copy"}</span>
          <Btn kind="primary" disabled={!canWrite} onClick={() => paste()}><ClipboardPaste size={12} /> Paste here</Btn>
          <Btn onClick={() => setClip(null)}>Cancel</Btn>
        </div>
      )}

      <div ref={listRef} tabIndex={0} aria-label={`Files in ${root}/${path}`}
        onDragOver={handlersHere.dropOver} onDragLeave={dragLeave} onDrop={handlersHere.drop}
        onContextMenu={(e) => { if (e.target === e.currentTarget || e.target.dataset.empty) { e.preventDefault(); setSelected(new Set()); setMenu({ x: e.clientX, y: e.clientY, target: null }); } }}
        onClick={(e) => { if (e.target === e.currentTarget) setSelected(new Set()); }}
        className={`flex-1 min-h-0 overflow-auto outline-none ${u.t.panel} ${drop?.kind === "here" ? "outline outline-2 outline-emerald-400" : ""}`}>
        {fm.unsupported ? (
          <div className="p-6 text-center text-xs opacity-70">The file manager API is not available on this Moonraker ({fm.error}).</div>
        ) : fm.error && !fm.entries.length ? (
          <div className="p-6 text-center text-xs space-y-2"><div className="text-red-400">{fm.error}</div><Btn onClick={fmRefresh}>Try again</Btn></div>
        ) : prefs.view === "list" ? (
          <div role="grid" aria-rowcount={rows.length}>
            <ListHeader cols={cols} sort={prefs.sort} onSort={(k) => setPref({ sort: { key: k, dir: prefs.sort.key === k && prefs.sort.dir === "asc" ? "desc" : "asc" } })} />
            {path && <ParentRow cols={cols} dropTarget={drop?.kind === "row" && drop.key === parentPath(path)} onOpen={() => go(root, parentPath(path))}
              onDragOver={dragOverFor("row", parentPath(path), canWrite)} onDragLeave={dragLeave} onDrop={dropHandlerFor(parentPath(path))} />}
            {rows.map((e) => (
              <ListRow key={e.path} entry={e} cols={cols} selected={selected.has(e.path)} dropTarget={drop?.kind === "row" && drop.key === e.path}
                active={isActiveFile(e)} thumbSrc={thumbSrc(e)} thumbSize={Math.min(prefs.thumb, 56)} showThumb={showThumbs} dateFormat={dateFormat} handlers={rowHandlers} />
            ))}
          </div>
        ) : (
          <div role="grid" className="flex flex-wrap gap-1 p-2">
            {path && <button type="button" onClick={() => go(root, parentPath(path))} className="px-3 py-2 text-xs font-mono opacity-70 hover:opacity-100">.. up</button>}
            {rows.map((e) => (
              <GridCard key={e.path} entry={e} selected={selected.has(e.path)} dropTarget={drop?.kind === "row" && drop.key === e.path} active={isActiveFile(e)}
                thumbSrc={thumbSrc(e)} thumbSize={prefs.thumb} handlers={rowHandlers} />
            ))}
          </div>
        )}
        {!fm.loading && !fm.error && !rows.length && (
          <div data-empty="1" className="p-8 text-center text-xs opacity-50 italic">
            {total ? "No files match the current filter." : canWrite ? "This folder is empty. Drop files here to upload them." : "This folder is empty."}
          </div>
        )}
        {hiddenCount > 0 && !search && <div className="px-3 py-2 text-[10px] opacity-40">{hiddenCount} item{hiddenCount > 1 ? "s" : ""} hidden by the filters.</div>}
        {fm.loading && <div className="px-3 py-2 text-[10px] opacity-50">Loading…</div>}
      </div>

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems()} onClose={() => setMenu(null)} />}
      <UploadTray />
      <Toast toast={toast} onClose={closeToast} />

      {finder && <QuickFinder root={root} onClose={() => setFinder(false)} onPick={(f) => {
        setFinder(false);
        const dir = parentPath(f.path);
        fmOpen(root, dir).then(() => {
          const entry = useStore.getState().fm.entries.find((e) => e.path === f.path);
          setSelected(new Set([f.path]));
          if (entry) open(entry);
        });
      }} />}

      {preview && <FilePreview entry={preview} root={root} onClose={() => setPreview(null)} canPrint={!printBusy} canPreheat={canPreheat(preview)}
        actions={{ print: doPrint, queue: doQueue, preheat: doPreheat, refreshMeta: doRefreshMeta, edit: doEdit, download: doDownload }} />}

      {editing && (
        <Suspense fallback={<div className="fixed inset-0 z-[80] bg-black/60 flex items-center justify-center text-sm text-white">Loading editor…</div>}>
          <EditorModal root={root} path={editing.path} writable={canWrite} onClose={() => { setEditing(null); fmRefresh(); }} />
        </Suspense>
      )}

      {dialog?.type === "rename" && <NameDialog title="Rename" label="New name" initial={dialog.entry.name} confirmLabel="Rename" onClose={() => setDialog(null)} onSubmit={(n) => submitRename(dialog.entry, n)} />}
      {dialog?.type === "mkdir" && <NameDialog title="New folder" label={`Folder name (in ${root}/${path})`} confirmLabel="Create" onClose={() => setDialog(null)} onSubmit={submitMkdir} />}
      {dialog?.type === "print" && (
        <ConfirmDialog title="Start print" confirmLabel="Start print" onClose={() => setDialog(null)} onConfirm={() => confirmPrint(dialog.entry)}>
          <p>Start printing <b className="font-mono">{dialog.entry.path}</b> now?</p>
          <p className="opacity-60">Make sure the bed is clear and the right filament is loaded.</p>
        </ConfirmDialog>
      )}
      {dialog?.type === "queue" && <QueueAddDialog names={dialog.names} onClose={() => setDialog(null)} onSubmit={(o) => submitQueue(dialog.names, o)} />}
      {dialog?.type === "delete" && (
        <ConfirmDialog title="Delete" danger confirmLabel="Delete" onClose={() => setDialog(null)} onConfirm={() => confirmDelete(dialog.entries)}>
          <p>Delete {dialog.entries.length > 1 ? `these ${dialog.entries.length} items` : "this item"} from <b>{root}</b>? This can not be undone.</p>
          <NameList names={dialog.entries.map((e) => e.path + (e.type === "dir" ? "/" : ""))} />
        </ConfirmDialog>
      )}
      {dialog?.type === "delete-nonempty" && (
        <ConfirmDialog title="Delete folders with their contents?" danger confirmLabel="Delete everything" onClose={() => setDialog(null)} onConfirm={() => confirmDelete(dialog.entries, true)}>
          <WarnLine>These folders are not empty. Everything inside them is deleted too.</WarnLine>
          <NameList names={dialog.folders.map((f) => `${f}/`)} />
        </ConfirmDialog>
      )}
      {dialog?.type === "overwrite" && (
        <ConfirmDialog title="Replace existing files?" danger confirmLabel="Replace" onClose={() => setDialog(null)}
          onConfirm={async () => { const r = await fmTransfer(dialog.kind, dialog.srcRoot || clip?.root || root, dialog.items, dialog.destDir, { destRoot: dialog.destRoot, overwrite: true }); setDialog(null); note(r.ok ? "Done" : r.message, r.ok); }}>
          <WarnLine>These already exist in the destination and will be replaced:</WarnLine>
          <NameList names={dialog.conflicts || []} />
        </ConfirmDialog>
      )}
    </div>
  );
}

