import React, { useEffect, useState, useMemo } from "react";
import {
  Files, Trash2, Play, Clock, Layers, RefreshCw, Download, Search,
  Folder, FolderPlus, ArrowUpLeft, ArrowUp, ArrowDown
} from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { formatDate } from "./dateFormat";

function formatBytes(n) {
  if (!n) return "0 KB";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  if (!seconds) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatWhen(unixSeconds, dateFormat) {
  if (!unixSeconds) return "";
  const d = new Date(unixSeconds * 1000);
  if (!dateFormat || dateFormat === "browser") {
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return formatDate(d, dateFormat);
}

function FileRow({ file }) {
  const metadata       = useStore((s) => s.gcodeMetadata[file.path]);
  const fetchMetadata  = useStore((s) => s.fetchGcodeMetadata);
  const deleteFile     = useStore((s) => s.deleteGcodeFile);
  const startPrintFile = useStore((s) => s.startPrintFile);
  const dateFormat     = useStore((s) => s.uiPrefs.dateFormat);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const [busy, setBusy] = useState(false);

  useEffect(() => { fetchMetadata(file.path); }, [fetchMetadata, file.path]);

  const meta = (metadata && metadata !== "loading" && metadata !== "error") ? metadata : null;
  const thumb = meta?.thumbnails?.find((th) => th.width >= 100) ?? meta?.thumbnails?.[0];
  const thumbUrl = thumb
    ? `${API}/api/v1/printer/files/gcodes/${encodeURIComponent(
        (file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/") + 1) : "") + thumb.relative_path
      )}`
    : null;

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${file.path}"? This can't be undone.`)) return;
    setBusy(true);
    await deleteFile(file.path);
    setBusy(false);
  };

  const handlePrint = async () => {
    if (!window.confirm(`Start printing "${file.path}" now?`)) return;
    setBusy(true);
    await startPrintFile(file.path);
    setBusy(false);
  };

  const displayName = file.path.split("/").pop();

  return (
    <div className={`flex items-center gap-3 px-3 py-2 text-xs ${t.cell}`}>
      <div className={`w-10 h-10 shrink-0 flex items-center justify-center overflow-hidden ${brutalist ? "border-2 border-[#111]" : "rounded bg-black/10"}`}>
        {thumbUrl
          ? <img src={thumbUrl} alt="" className="w-full h-full object-cover" onError={(e) => { e.target.style.display = "none"; }} />
          : <Layers size={16} className="opacity-30" />}
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate font-mono font-medium" title={file.path}>{displayName}</div>
        <div className="flex items-center gap-2 opacity-50 text-[10px] mt-0.5">
          <span>{formatBytes(file.size)}</span>
          <span>·</span>
          <span>{formatWhen(file.modified, dateFormat)}</span>
          {meta?.estimated_time && (
            <><span>·</span><span className="flex items-center gap-1"><Clock size={9} />{formatDuration(meta.estimated_time)}</span></>
          )}
          {meta?.filament_weight_total && (
            <><span>·</span><span>{meta.filament_weight_total.toFixed(0)}g</span></>
          )}
        </div>
      </div>

      <div className="w-20 text-right font-mono text-[11px] opacity-60 hidden sm:block">
        {formatBytes(file.size)}
      </div>

      <div className="w-24 text-right font-mono text-[10px] opacity-50 hidden md:block">
        {formatWhen(file.modified, dateFormat)}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <a
          href={`${API}/api/v1/printer/files/gcodes/${encodeURIComponent(file.path)}`}
          download={displayName}
          title="Download file to computer"
          className={`p-1.5 flex items-center justify-center rounded ${t.chip} ${
            brutalist ? "bg-[#FFE9A8] text-[#111] border-2 border-[#111]" : "bg-blue-800 hover:bg-blue-700 text-white"
          }`}
        >
          <Download size={12} />
        </a>
        <button onClick={handlePrint} disabled={busy} title="Print this file"
          className={`p-1.5 ${t.chip} ${brutalist ? "bg-[#B7E4C7]" : "bg-emerald-700 hover:bg-emerald-600 text-white"}`}>
          <Play size={12} />
        </button>
        <button onClick={handleDelete} disabled={busy} title="Delete"
          className={`p-1.5 ${t.chip} ${brutalist ? "bg-[#F4A6A0]" : "bg-red-800 hover:bg-red-700 text-white"}`}>
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}

function FolderRow({ folder, onOpen, onDelete }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  return (
    <div
      onClick={() => onOpen(folder.path)}
      className={`flex items-center gap-3 px-3 py-2 text-xs cursor-pointer select-none transition-colors ${t.cell} hover:border-blue-400 group`}
    >
      <div className={`w-10 h-10 shrink-0 flex items-center justify-center overflow-hidden ${
        brutalist ? "border-2 border-[#111] bg-[#FFE9A8]" : "rounded bg-blue-500/10 text-blue-400"
      }`}>
        <Folder size={18} className={brutalist ? "text-[#111]" : "text-blue-400"} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="font-mono font-bold truncate group-hover:text-blue-400 transition-colors flex items-center gap-1.5">
          <span>{folder.name}</span>
          <span className="text-[10px] font-normal opacity-50">/</span>
        </div>
        <div className="text-[10px] opacity-50 mt-0.5">
          Folder
        </div>
      </div>

      <div className="w-20 text-right font-mono text-[11px] opacity-40 hidden sm:block">
        —
      </div>

      <div className="w-24 text-right font-mono text-[10px] opacity-40 hidden md:block">
        —
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(folder.path);
          }}
          title="Delete folder"
          className={`p-1.5 ${t.chip} ${
            brutalist ? "bg-[#F4A6A0] text-[#111]" : "hover:bg-red-900/30 text-red-400 opacity-60 hover:opacity-100"
          }`}
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}

// ── File manager ─────────────────────────────────────────────────────────────
export function FileManager() {
  const files           = useStore((s) => s.gcodeFiles);
  const fetchFiles      = useStore((s) => s.fetchGcodeFiles);
  const createDirectory = useStore((s) => s.createDirectory);
  const deleteDirectory = useStore((s) => s.deleteDirectory);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const [loading, setLoading]       = useState(false);
  const [search, setSearch]         = useState("");
  const [currentPath, setCurrentPath] = useState("");
  const [sortField, setSortField]   = useState("name"); // "name" | "size" | "date"
  const [sortOrder, setSortOrder]   = useState("asc");  // "asc" | "desc"

  const normCurPath = currentPath.replace(/^\/+|\/+$/g, "");

  const refresh = async () => {
    setLoading(true);
    await fetchFiles();
    setLoading(false);
  };

  useEffect(() => { fetchFiles(); }, [fetchFiles]);

  const handleNewFolder = async () => {
    const name = window.prompt("Enter new folder name:");
    if (!name || !name.trim()) return;
    const cleanName = name.trim().replace(/[\\/:*?"<>|]/g, "");
    if (!cleanName) return;
    const target = normCurPath ? `${normCurPath}/${cleanName}` : cleanName;
    setLoading(true);
    await createDirectory(target);
    await fetchFiles();
    setLoading(false);
  };

  const handleDeleteFolder = async (folderPath) => {
    if (!window.confirm(`Delete folder "${folderPath}" and its contents? This cannot be undone.`)) return;
    setLoading(true);
    await deleteDirectory(folderPath);
    await fetchFiles();
    setLoading(false);
  };

  const handleSort = (field) => {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortOrder(field === "date" ? "desc" : "asc");
    }
  };

  // Extract items for current directory or global search
  const { currentFolders, currentFiles } = useMemo(() => {
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      const matched = files.filter((f) => (f.path || "").toLowerCase().includes(q));
      return { currentFolders: [], currentFiles: matched };
    }

    const folderMap = new Map();
    const fileList = [];

    files.forEach((item) => {
      // Check explicit directory item
      if (item.type === "directory" || item.dirname) {
        const dirPath = (item.dirname || item.path || "").replace(/^\/+|\/+$/g, "");
        if (normCurPath === "") {
          const topFolder = dirPath.split("/")[0];
          if (topFolder && !folderMap.has(topFolder)) {
            folderMap.set(topFolder, { name: topFolder, path: topFolder });
          }
        } else if (dirPath.startsWith(normCurPath + "/")) {
          const sub = dirPath.slice(normCurPath.length + 1);
          const nextFolder = sub.split("/")[0];
          if (nextFolder) {
            const fullP = `${normCurPath}/${nextFolder}`;
            if (!folderMap.has(fullP)) {
              folderMap.set(fullP, { name: nextFolder, path: fullP });
            }
          }
        }
        return;
      }

      // Handle file path
      const p = (item.path || "").replace(/^\/+/, "");
      if (normCurPath === "") {
        if (p.includes("/")) {
          const folderName = p.split("/")[0];
          if (!folderMap.has(folderName)) {
            folderMap.set(folderName, { name: folderName, path: folderName });
          }
        } else {
          fileList.push(item);
        }
      } else {
        if (p.startsWith(normCurPath + "/")) {
          const rest = p.slice(normCurPath.length + 1);
          if (rest.includes("/")) {
            const folderName = rest.split("/")[0];
            const fullFolder = `${normCurPath}/${folderName}`;
            if (!folderMap.has(fullFolder)) {
              folderMap.set(fullFolder, { name: folderName, path: fullFolder });
            }
          } else {
            fileList.push(item);
          }
        }
      }
    });

    return {
      currentFolders: Array.from(folderMap.values()),
      currentFiles: fileList,
    };
  }, [files, normCurPath, search]);

  // Sort folders and files
  const sortedFolders = useMemo(() => {
    return [...currentFolders].sort((a, b) => {
      const cmp = a.name.localeCompare(b.name);
      return sortOrder === "asc" ? cmp : -cmp;
    });
  }, [currentFolders, sortOrder]);

  const sortedFiles = useMemo(() => {
    return [...currentFiles].sort((a, b) => {
      let cmp = 0;
      if (sortField === "name") {
        const nameA = a.path.split("/").pop();
        const nameB = b.path.split("/").pop();
        cmp = nameA.localeCompare(nameB);
      } else if (sortField === "size") {
        cmp = (a.size || 0) - (b.size || 0);
      } else if (sortField === "date") {
        cmp = (a.modified || 0) - (b.modified || 0);
      }
      return sortOrder === "asc" ? cmp : -cmp;
    });
  }, [currentFiles, sortField, sortOrder]);

  const pathSegments = normCurPath ? normCurPath.split("/") : [];

  const handleGoUp = () => {
    if (!normCurPath) return;
    const idx = normCurPath.lastIndexOf("/");
    setCurrentPath(idx !== -1 ? normCurPath.slice(0, idx) : "");
  };

  const totalItemsCount = search.trim()
    ? sortedFiles.length
    : sortedFolders.length + sortedFiles.length;

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-3">
      {/* Top Header & Actions Bar */}
      <div className={`flex flex-wrap items-center justify-between gap-2 px-4 py-3 ${t.panel}`}>
        <div className="flex items-center gap-2">
          <Files size={18} className="text-blue-500" />
          <h2 className={t.heading}>
            Files ({totalItemsCount})
          </h2>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {/* New Folder Button */}
          <button
            type="button"
            onClick={handleNewFolder}
            title="Create new folder"
            className={`flex items-center gap-1 px-2.5 py-1 text-xs font-bold rounded ${
              brutalist ? "border-2 border-[#111] bg-[#FFE9A8] text-[#111]" : "bg-emerald-600 hover:bg-emerald-500 text-white"
            }`}
          >
            <FolderPlus size={13} />
            <span className="hidden sm:inline">New Folder</span>
          </button>

          {/* Search Input */}
          <div className="relative flex items-center">
            <Search size={12} className="absolute left-2.5 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search files..."
              className={`pl-7 pr-2 py-1 text-xs font-mono rounded outline-none w-32 sm:w-44 ${
                brutalist
                  ? "border-2 border-[#111] bg-white text-[#111]"
                  : "bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:border-blue-500"
              }`}
            />
          </div>

          <button onClick={refresh} disabled={loading} className="opacity-60 hover:opacity-100 p-1" title="Refresh files list">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Breadcrumb Navigation Bar (when not searching) */}
      {!search.trim() && (
        <div className={`flex items-center gap-1 px-4 py-1.5 text-xs font-mono rounded-lg overflow-x-auto ${
          brutalist ? "bg-white border-2 border-[#111] text-[#111]" : "bg-black/10 border border-white/5 text-gray-300"
        }`}>
          <span className="opacity-50 text-[10px] uppercase font-bold mr-1">Path:</span>
          <button
            onClick={() => setCurrentPath("")}
            className={`px-1.5 py-0.5 rounded font-bold transition-colors ${
              normCurPath === "" ? "bg-blue-600 text-white" : "opacity-70 hover:opacity-100 hover:underline"
            }`}
          >
            / (gcodes)
          </button>
          {pathSegments.map((segment, idx) => {
            const subPath = pathSegments.slice(0, idx + 1).join("/");
            const isLast = idx === pathSegments.length - 1;
            return (
              <React.Fragment key={subPath}>
                <span className="opacity-40">/</span>
                <button
                  onClick={() => setCurrentPath(subPath)}
                  className={`px-1.5 py-0.5 rounded font-bold transition-colors ${
                    isLast ? "bg-blue-600 text-white" : "opacity-70 hover:opacity-100 hover:underline"
                  }`}
                >
                  {segment}
                </button>
              </React.Fragment>
            );
          })}
        </div>
      )}

      {/* Column Sort Header */}
      <div className={`flex items-center gap-3 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider opacity-60 border-b ${
        brutalist ? "border-b-2 border-[#111]" : t.border
      }`}>
        <div className="w-10 shrink-0 text-center">Type</div>
        <button
          type="button"
          onClick={() => handleSort("name")}
          className="flex-1 flex items-center gap-1 text-left hover:opacity-100 hover:text-blue-400"
        >
          <span>Name</span>
          {sortField === "name" && (sortOrder === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
        </button>
        <button
          type="button"
          onClick={() => handleSort("size")}
          className="w-20 text-right hidden sm:flex items-center justify-end gap-1 hover:opacity-100 hover:text-blue-400"
        >
          <span>Size</span>
          {sortField === "size" && (sortOrder === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
        </button>
        <button
          type="button"
          onClick={() => handleSort("date")}
          className="w-24 text-right hidden md:flex items-center justify-end gap-1 hover:opacity-100 hover:text-blue-400"
        >
          <span>Date</span>
          {sortField === "date" && (sortOrder === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
        </button>
        <div className="w-24 text-right shrink-0">Actions</div>
      </div>

      {/* Files & Folders List */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5 pr-1">
        {/* Go Up Row if in subfolder */}
        {!search.trim() && normCurPath !== "" && (
          <div
            onClick={handleGoUp}
            className={`flex items-center gap-3 px-3 py-2 text-xs cursor-pointer select-none transition-colors ${t.cell} hover:border-emerald-400 text-emerald-400 font-bold font-mono`}
          >
            <div className="w-10 h-8 shrink-0 flex items-center justify-center">
              <ArrowUpLeft size={18} />
            </div>
            <span>.. (Up one level)</span>
          </div>
        )}

        {!search.trim() && sortedFolders.map((folder) => (
          <FolderRow
            key={folder.path}
            folder={folder}
            onOpen={setCurrentPath}
            onDelete={handleDeleteFolder}
          />
        ))}

        {sortedFiles.map((f) => (
          <FileRow key={f.path} file={f} />
        ))}

        {!sortedFolders.length && !sortedFiles.length && (
          <div className={`p-8 text-center text-xs opacity-40 italic ${t.panel}`}>
            {search.trim()
              ? "No files match your search."
              : normCurPath !== ""
                ? "This folder is currently empty."
                : "No gcode files found on the printer."}
          </div>
        )}
      </div>
    </div>
  );
}
