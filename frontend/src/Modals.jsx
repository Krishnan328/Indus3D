import React, { useState, useEffect } from "react";
import { Map, X, AlertTriangle, RefreshCw, FileText, Save, Power, Cpu } from "lucide-react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { API, useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

// The two modals below (HeightmapModal, ConfigEditor) are moved from App.jsx
// verbatim, unchanged logic — same fetch calls, same localStorage keys, same
// save/restart behavior. They're occasional-use surfaces, not part of the
// brutalist/pastel redesign, so left in their original dark/light styling
// rather than retrofitted with theme tokens.

function MeshVoxels({ meshData }) {
  if (!meshData.length) return null;
  const size = meshData.length;
  const spacing = 12 / size;
  return <group>{meshData.flatMap((row, z) => row.map((height, x) => {
    const color = height > 0.05 ? "#ef4444" : height < -0.05 ? "#3b82f6" : "#22c55e";
    return <mesh key={`${x}-${z}`} position={[x * spacing - 6, height * 10, z * spacing - 6]}><boxGeometry args={[spacing * 0.8, 0.2, spacing * 0.8]} /><meshStandardMaterial color={color} /></mesh>;
  }))}</group>;
}

// ── Heightmap Modal ───────────────────────────────────────────────────────────
export function HeightmapModal({ isDarkMode, onClose }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const themeName = useStore((s) => s.theme);

  const getThemeCanvasBg = () => {
    if (themeName === "creme") return "#F5F0E8";
    if (themeName === "blueprint") return "#d0e3ff";
    if (themeName === "workshop") return "#FDFBF7";
    return isDarkMode ? "#000000" : "#f3f4f6";
  };
  const canvasBg = getThemeCanvasBg();
  const [meshData,  setMeshData]  = useState([]);
  const [meshError, setMeshError] = useState(null);
  const [loadingMesh, setLoadingMesh] = useState(true);

  // Calibration date now comes from the backend, keyed per-printer (see
  // config/printers.py) — not browser localStorage. Klipper's bed_mesh
  // status has no timestamp of its own, and a localStorage-only date would
  // show the wrong age after switching active printers.
  const printerInstances = useStore((s) => s.printerInstances);
  const fetchPrinterInstances = useStore((s) => s.fetchPrinterInstances);
  const activePrinter = printerInstances.printers.find((p) => p.id === printerInstances.active);
  const lastCalibIso = activePrinter?.last_mesh_calibration || null;
  const calibDate = lastCalibIso ? new Date(lastCalibIso).toLocaleDateString() : "Unknown";
  const needsRecal = !lastCalibIso || (new Date() - new Date(lastCalibIso)) / 86400000 > 14;

  const [isCalib,   setIsCalib]   = useState(false);

  useEffect(() => {
    fetchPrinterInstances();
    (async()=>{
      setLoadingMesh(true);
      setMeshError(null);
      try {
        const res = await fetch(`${API}/api/v1/printer/bedmesh`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const points = data.result?.status?.bed_mesh?.probed_matrix ?? data.result?.status?.bed_mesh?.profiles?.default?.points;
        if (!points || !points.length) {
          setMeshError("No bed mesh is currently loaded on the printer. Run Auto-Level to generate one.");
          setMeshData([]);
        } else {
          setMeshData(points);
        }
      } catch {
        setMeshError("Could not reach the printer for mesh data. Check that Moonraker is running and reachable.");
        setMeshData([]);
      }
      setLoadingMesh(false);
    })();
  }, [fetchPrinterInstances]);

  const handleCalibrate = async () => {
    setIsCalib(true);
    try {
      const res = await fetch(`${API}/api/v1/printer/bedmesh/calibrate`, { method: "POST" });
      const data = await res.json();
      if (data.status !== "ok") throw new Error("Calibration failed");
      await fetchPrinterInstances(); // picks up the new last_mesh_calibration
      setTimeout(() => { setIsCalib(false); onClose(); }, 2000);
    } catch {
      setIsCalib(false);
      setMeshError("Auto-level failed to start. Check the printer connection and try again.");
    }
  };

  const borderClass = brutalist ? "border-[#111] border-[3px]" : `border ${t.border}`;

  return (
    <div className="absolute inset-0 z-[200] flex flex-col bg-black/80 backdrop-blur-md p-4 sm:p-8">
      <div className={`w-full h-full flex flex-col rounded-2xl overflow-hidden shadow-2xl ${t.panel}`}>
        {/* Header */}
        <div className={`px-6 py-4 flex justify-between items-center shrink-0 ${brutalist ? "border-b-[3px] border-[#111]" : `border-b ${t.border}`}`}>
          <div className="flex items-center gap-3 text-emerald-500">
            <Map size={24}/>
            <h2 className={t.heading}>Surface Topography</h2>
          </div>
          <button onClick={onClose} className="p-2 rounded-full bg-gray-500/10 hover:bg-gray-500/20 transition-colors"><X size={24}/></button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
          <div className={`w-full md:w-80 shrink-0 p-6 flex flex-col gap-6 ${brutalist ? "border-r-[3px] border-[#111] bg-black/5" : `border-r ${t.border} bg-black/5`}`}>
            <div>
              <h3 className={t.label}>Calibration Tracker</h3>
              <div className={`mt-2 p-4 rounded-xl ${borderClass} ${needsRecal ? "bg-yellow-500/10 border-yellow-500/50" : "bg-black/5"}`}>
                <span className="block text-[10px] uppercase tracking-widest opacity-70 mb-1">Last Probed (via Indus3D)</span>
                <span className="font-mono text-xl font-bold">{calibDate}</span>
                {needsRecal && <div className="flex items-center gap-2 mt-3 text-xs font-bold text-yellow-500 animate-pulse"><AlertTriangle size={14}/>MESH OUTDATED</div>}
              </div>
              <p className="text-[10px] opacity-40 mt-2 leading-relaxed">
                Only tracks calibrations run from this button — Klipper doesn't record a probe timestamp itself, so a mesh calibrated another way (console, macro) will still show as "Unknown" here.
              </p>
            </div>

            <button onClick={handleCalibrate} disabled={isCalib}
              className={`mt-auto flex items-center justify-center gap-2 w-full py-4 rounded-xl font-bold text-sm uppercase tracking-widest transition-all ${isCalib ? "bg-black/50 opacity-50 cursor-not-allowed" : (brutalist ? "bg-emerald-300 border-[3px] border-[#111] text-[#111] hover:bg-emerald-400" : "bg-emerald-500 text-white hover:bg-emerald-400")}`}>
              <RefreshCw size={18} className={isCalib ? "animate-spin" : ""} />
              {isCalib ? "Probing..." : "Run Auto-Level"}
            </button>
            {meshError && (
              <div className="p-3 rounded-lg bg-red-500/10 text-red-400 text-xs leading-relaxed">
                {meshError}
              </div>
            )}
          </div>

          <div className={`flex-1 relative`} style={{ backgroundColor: canvasBg }}>
            {loadingMesh ? (
              <div className="absolute inset-0 flex items-center justify-center text-sm opacity-40 font-mono">Loading mesh…</div>
            ) : meshData.length === 0 ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm opacity-40 font-mono text-center px-6">
                <AlertTriangle size={28} />
                {meshError || "No mesh data available."}
              </div>
            ) : (
              <Canvas camera={{position:[0,15,20],fov:45}}>
                <color attach="background" args={[isDarkMode ? "#000000" : "#f3f4f6"]} />
                <ambientLight intensity={0.5}/><directionalLight position={[10,20,10]} intensity={1.5}/>
                <MeshVoxels meshData={meshData} /><OrbitControls makeDefault enableDamping dampingFactor={0.2}/>
              </Canvas>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Config Editor ─────────────────────────────────────────────────────────────
export function ConfigEditor({ isDarkMode, onClose }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const themeName = useStore((s) => s.theme);
  const uiPrefs = useStore((s) => s.uiPrefs);

  const getThemeBg = () => {
    if (themeName === "creme") return "#F5F0E8";
    if (themeName === "blueprint") return "#d0e3ff";
    if (themeName === "workshop") return "#FDFBF7";
    return isDarkMode ? "#1e1e1e" : "#ffffff";
  };
  const getThemeText = () => {
    if (themeName === "creme") return "text-emerald-900";
    if (themeName === "blueprint") return "text-[#103b8c]";
    if (themeName === "workshop") return "text-[#111]";
    return isDarkMode ? "text-gray-300" : "text-gray-800";
  };
  const getThemeActiveItem = () => {
    if (themeName === "creme") return "border-emerald-600 bg-emerald-600/10 font-bold text-emerald-900";
    if (themeName === "blueprint") return "border-[#103b8c] bg-[#103b8c]/10 font-bold text-[#103b8c]";
    if (themeName === "workshop") return "border-[#111] bg-black/10 font-bold text-black";
    return isDarkMode ? "border-blue-500 bg-blue-500/20 font-bold" : "border-blue-500 bg-blue-500/10 font-bold";
  };
  const [files, setFiles] = useState([]);
  const [filesError, setFilesError] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState(""); // last loaded/saved snapshot, for dirty-check
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  const isDirty = content !== savedContent;

  useEffect(() => {
    (async()=>{
      try {
        const res = await fetch(`${API}/api/v1/printer/files/config`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const confFiles = (data.result || []).filter(f => f.path.endsWith(".cfg") || f.path.endsWith(".conf"));
        setFiles(confFiles);
        setFilesError(null);
        if (confFiles.length > 0) {
          const firstFile = confFiles[0].path;
          setSelectedFile(firstFile);
          const fileRes = await fetch(`${API}/api/v1/printer/files/config/${encodeURIComponent(firstFile)}`);
          if (!fileRes.ok) throw new Error(`HTTP ${fileRes.status}`);
          const firstFileContent = await fileRes.text();
          setContent(firstFileContent);
          setSavedContent(firstFileContent);
        }
        setLoading(false);
      } catch {
        // Be honest about the failure instead of presenting fake files as real.
        setFiles([]);
        setFilesError("Could not reach the config file list. Check that the Indus3D API and Moonraker are running.");
        setLoading(false);
      }
    })();
  }, []);

  const handleSelectFile = async (path) => {
    if (isDirty && uiPrefs.editorConfirmUnsaved) {
      if (!window.confirm(`Discard unsaved changes to ${selectedFile}?`)) return;
    }
    setSelectedFile(path);
    setLoading(true);
    setSaveMsg("");
    try {
      const res = await fetch(`${API}/api/v1/printer/files/config/${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      setContent(text);
      setSavedContent(text);
    } catch {
      setContent("# Failed to load file");
      setSavedContent("# Failed to load file");
    }
    setLoading(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      const fd = new FormData();
      const blob = new Blob([content], { type: "text/plain" });
      fd.append("file", blob, selectedFile);
      const res = await fetch(`${API}/api/v1/printer/files/config/${encodeURIComponent(selectedFile)}`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSavedContent(content);
      setSaveMsg("Saved");
    } catch (e) {
      console.error("Save failed", e);
      setSaveMsg("Save failed");
    }
    setSaving(false);
    setTimeout(() => setSaveMsg(""), 3000);
  };

  const handleRestart = async () => {
    try { await fetch(`${API}/api/v1/printer/restart`, { method: "POST" }); onClose(); } catch {
      setSaveMsg("Restart failed");
    }
  };

  const requestClose = () => {
    if (isDirty && uiPrefs.editorConfirmUnsaved) {
      if (!window.confirm("Discard unsaved changes and close the editor?")) return;
    }
    onClose();
  };

  // Esc-to-close (respects the "confirm unsaved" setting above), and
  // Tab-inserts-spaces at the cursor instead of shifting focus away.
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape" && uiPrefs.editorCloseOnEsc) {
        e.preventDefault();
        requestClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uiPrefs.editorCloseOnEsc, isDirty, content, savedContent, selectedFile]);

  const handleTextareaKeyDown = (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const el = e.target;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const spaces = " ".repeat(Math.max(1, uiPrefs.editorTabSize || 2));
    const next = content.slice(0, start) + spaces + content.slice(end);
    setContent(next);
    // Restore cursor position after the inserted spaces (post-render).
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + spaces.length;
    });
  };

  return (
    <div className="absolute inset-0 z-[200] flex flex-col bg-black/80 backdrop-blur-md p-4 sm:p-8">
      <div className={`w-full h-full flex flex-col rounded-2xl overflow-hidden shadow-2xl ${t.panel}`}>
        {/* Header */}
        <div className={`px-6 py-4 flex justify-between items-center shrink-0 ${brutalist ? "border-b-[3px] border-[#111]" : `border-b ${t.border}`}`}>
          <div className="flex items-center gap-3 text-blue-500">
            <FileText size={24}/>
            <h2 className={t.heading}>Configuration Editor</h2>
            {isDirty && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-500 font-bold tracking-wide">UNSAVED</span>}
            {saveMsg && <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold tracking-wide ${saveMsg === "Saved" ? "bg-emerald-500/20 text-emerald-500" : "bg-red-500/20 text-red-500"}`}>{saveMsg.toUpperCase()}</span>}
          </div>
          <button onClick={requestClose} className="p-2 rounded-full bg-gray-500/10 hover:bg-gray-500/20 transition-colors"><X size={24}/></button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
          {/* Sidebar */}
          <div className={`w-full md:w-64 shrink-0 overflow-y-auto ${brutalist ? "border-r-[3px] border-[#111] bg-black/5" : `border-r ${t.border} bg-black/5`}`}>
            <div className={`p-4 ${t.label}`}>Config Files</div>
            {files.length === 0 && !filesError && <div className="px-4 text-xs opacity-50 italic">Loading...</div>}
            {filesError && <div className="px-4 pb-4 text-xs text-red-500">{filesError}</div>}
            {files.map(f => (
              <button key={f.path} onClick={() => handleSelectFile(f.path)}
                className={`w-full text-left px-4 py-3 text-sm transition-colors border-l-4 ${selectedFile === f.path ? getThemeActiveItem() : "border-transparent opacity-70 hover:opacity-100 hover:bg-black/5"}`}>
                {f.path}{selectedFile === f.path && isDirty ? " •" : ""}
              </button>
            ))}
          </div>

          {/* Editor */}
          <div className={`flex-1 flex flex-col relative`} style={{ backgroundColor: getThemeBg() }}>
            {loading ? (
              <div className="flex-1 flex items-center justify-center text-gray-400 font-mono text-sm">Loading {selectedFile}...</div>
            ) : !selectedFile ? (
              <div className="flex-1 flex items-center justify-center text-gray-400 font-mono text-sm text-center px-6">
                {filesError || "No config files available."}
              </div>
            ) : (
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                onKeyDown={handleTextareaKeyDown}
                className={`flex-1 w-full h-full p-4 bg-transparent font-mono text-sm resize-none focus:outline-none ${getThemeText()}`}
                spellCheck="false"
              />
            )}

            {/* Actions */}
            <div className="absolute bottom-6 right-6 flex gap-3">
              <button onClick={handleSave} disabled={saving || !selectedFile}
                className={`flex items-center gap-2 px-5 py-3 rounded-xl font-bold text-sm transition-all disabled:opacity-40 ${brutalist ? "bg-blue-400 border-[3px] border-[#111] text-[#111] hover:bg-blue-500" : "bg-blue-600 text-white shadow-lg hover:bg-blue-500"}`}>
                <Save size={18}/> {saving ? "Saving..." : "Save File"}
              </button>
              <button onClick={handleRestart}
                className={`flex items-center gap-2 px-5 py-3 rounded-xl font-bold text-sm transition-all ${brutalist ? "bg-red-400 border-[3px] border-[#111] text-[#111] hover:bg-red-500" : "bg-red-600 text-white shadow-lg hover:bg-red-500"}`}>
                <RefreshCw size={18}/> Firmware Restart
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function PowerModal({ onClose }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const powerAction = useStore(s => s.powerAction);

  const actions = [
    { id: "emergency_stop", label: "Emergency Stop", icon: AlertTriangle, color: "text-red-500", desc: "M112 Halt Printer" },
    { id: "restart", label: "Restart Klipper", icon: RefreshCw, color: "text-blue-500", desc: "Restart Klipper Host Software" },
    { id: "firmware_restart", label: "Firmware Restart", icon: Cpu, color: "text-purple-500", desc: "Reboot MCU & Restart Klipper" },
    { id: "reboot", label: "Reboot Host", icon: Power, color: "text-orange-500", desc: "Reboot the Raspberry Pi / Host" },
    { id: "shutdown", label: "Power Off Host", icon: Power, color: "text-red-500", desc: "Shutdown the Raspberry Pi / Host" },
  ];

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 ${t.text}`}>
      <div className={`w-full max-w-sm ${t.panelSolid} p-4 flex flex-col gap-4 shadow-xl ${brutalist ? "rounded-none border-4 border-[#111]" : "rounded-2xl border border-white/10"}`}>
        <div className="flex justify-between items-center">
          <h2 className={t.heading}>Power Control</h2>
          <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-col gap-2 mt-2">
          {actions.map(a => {
            const Icon = a.icon;
            return (
              <button
                key={a.id}
                onClick={() => {
                  if (a.id === "emergency_stop" || window.confirm(`Are you sure you want to ${a.label}?`)) {
                    powerAction(a.id);
                    onClose();
                  }
                }}
                className={`flex items-center gap-4 p-3 text-left transition-colors ${brutalist ? "border-2 border-[#111] hover:bg-[#111] hover:text-white" : "rounded-xl border border-white/5 bg-black/20 hover:bg-white/10"}`}
              >
                <Icon size={24} className={brutalist ? "text-current" : a.color} />
                <div className="flex flex-col">
                  <span className="font-bold text-sm">{a.label}</span>
                  <span className="text-xs opacity-60">{a.desc}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
