/**
 * PrintStatusCard.jsx
 * --------------------
 * Shows active print progress, ETA, speed/flow factors,
 * pause/resume/cancel controls, and file upload button.
 * Drop into the Live tab sidebar in App.jsx,
 * replacing the static FILE/BYTE overlay in the 3D viewport.
 */

import React, { useRef, useState } from "react";
import {
  Upload, Play, Pause, Square, Clock, Percent,
  Gauge, Layers,
} from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { SpoolPicker } from "./SpoolPicker";

const formatTime = (seconds) => {
  if (!seconds || seconds <= 0) return "--:--:--";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
};

const formatDuration = (seconds) => {
  if (!seconds) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

export function PrintStatusCard({ isDarkMode }) {
  const state = useStore((s) => s.telemetry?.state);
  const filename = useStore((s) => s.telemetry?.filename);
  const progress = useStore((s) => s.telemetry?.progress) || 0;
  const z = useStore((s) => s.telemetry?.z);
  const speed_factor = useStore((s) => s.telemetry?.speed_factor);
  const flow_factor = useStore((s) => s.telemetry?.flow_factor);
  const print_duration = useStore((s) => s.telemetry?.print_duration);
  const time_remaining = useStore((s) => s.telemetry?.time_remaining);
  const pausePrint  = useStore((s) => s.pausePrint);
  const resumePrint = useStore((s) => s.resumePrint);
  const cancelPrint = useStore((s) => s.cancelPrint);
  const uploadAndPrint = useStore((s) => s.uploadAndPrint);
  const confirmCancelPrint = useStore((s) => s.uiPrefs.confirmCancelPrint);
  const hideUploadButton   = useStore((s) => s.uiPrefs.hideUploadButton);

  const [uploading, setUploading]   = useState(false);
  const [uploadMsg, setUploadMsg]   = useState("");
  const [cancelling, setCancelling] = useState(false);
  const fileRef = useRef();


  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const isPrinting = state === "printing";
  const isPaused   = state === "paused";
  const isIdle     = !isPrinting && !isPaused;

  const progressPercent = (progress ?? 0) * 100;
  const shortname  = filename?.length > 28 ? "…" + filename.slice(-26) : (filename || "No active file");

  const cell  = brutalist ? "border-[2px] border-[#111] bg-white text-[#111]" : (isDarkMode ? "bg-gray-900 border border-gray-800 text-gray-200" : "bg-white border border-gray-200 text-gray-700");
  const label = "text-[9px] uppercase tracking-widest block mb-1 opacity-60";

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadMsg("Uploading…");
    try {
      const res = await uploadAndPrint(file, true);
      setUploadMsg(res.status === "ok" ? `✅ Started: ${file.name}` : `❌ ${res.error}`);
    } catch {
      setUploadMsg("❌ Upload failed");
    }
    setUploading(false);
    setTimeout(() => setUploadMsg(""), 4000);
    e.target.value = "";
  };

  const handleCancel = async () => {
    if (confirmCancelPrint && !window.confirm("Cancel the current print?")) return;
    setCancelling(true);
    await cancelPrint();
    setCancelling(false);
  };

  return (
    <div className={`h-full p-4 flex flex-col gap-3 ${t.panel}`}>
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-blue-500">
          <Layers size={16} className={brutalist ? "text-[#111]" : ""} />
          <h3 className={t.heading}>Print Status</h3>
        </div>
        <div className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-widest ${brutalist ? "border-2 border-[#111]" : ""}
          ${isPrinting ? (brutalist ? "bg-[#32E0C4] text-[#111]" : "bg-green-700 text-white")
            : isPaused  ? (brutalist ? "bg-[#FFD166] text-[#111]" : "bg-yellow-600 text-white")
            : (brutalist ? "bg-gray-200 text-[#111]" : "bg-gray-700 text-gray-300")}`}>
          {state || "standby"}
        </div>
      </div>

      {/* Filename */}
      {filename && (
        <div className={`px-3 py-2 rounded-lg font-mono text-[10px] truncate shrink-0 ${cell}`}>
          {shortname}
        </div>
      )}

      {/* Progress bar */}
      <div className="shrink-0">
        <div className="flex justify-between text-[10px] font-mono opacity-60 mb-1">
          <span>{progressPercent.toFixed(1)}%</span>
          <span>Elapsed: {formatDuration(print_duration)}</span>
        </div>
        <div className={`w-full h-3 rounded-full overflow-hidden ${brutalist ? "border-2 border-[#111] bg-white" : (isDarkMode ? "bg-gray-800" : "bg-gray-200")}`}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(progressPercent, 100)}%`,
              background: isPaused
                ? "linear-gradient(90deg, #d97706, #f59e0b)"
                : (brutalist ? "#32E0C4" : "linear-gradient(90deg, #2563eb, #06b6d4)"),
            }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2 text-center font-mono text-xs shrink-0">
        <div className={`p-2 rounded ${cell}`}>
          <span className={label}><Clock size={9} className="inline mr-1"/>ETA</span>
          {formatTime(time_remaining)}
        </div>
        <div className={`p-2 rounded ${cell}`}>
          <span className={label}>Layer Z</span>
          {(z ?? 0).toFixed(2)} mm
        </div>
        <div className={`p-2 rounded ${cell}`}>
          <span className={label}><Gauge size={9} className="inline mr-1"/>Speed</span>
          {speed_factor ?? 100}%
        </div>
        <div className={`p-2 rounded ${cell}`}>
          <span className={label}><Percent size={9} className="inline mr-1"/>Flow</span>
          {flow_factor ?? 100}%
        </div>
      </div>

      {/* Controls */}
      <div className="flex gap-2 shrink-0">
        {isPrinting && (
          <button onClick={pausePrint}
            className={`flex-1 flex items-center justify-center gap-1 py-2 ${brutalist ? "bg-[#FFD166] border-2 border-[#111] text-[#111] hover:bg-yellow-300" : "bg-yellow-600 hover:bg-yellow-500 text-white"} rounded-lg text-xs font-bold uppercase tracking-widest transition-colors`}>
            <Pause size={13} /> Pause
          </button>
        )}
        {isPaused && (
          <button onClick={resumePrint}
            className={`flex-1 flex items-center justify-center gap-1 py-2 ${brutalist ? "bg-[#32E0C4] border-2 border-[#111] text-[#111] hover:bg-green-300" : "bg-green-600 hover:bg-green-500 text-white"} rounded-lg text-xs font-bold uppercase tracking-widest transition-colors`}>
            <Play size={13} /> Resume
          </button>
        )}
        {(isPrinting || isPaused) && (
          <button onClick={handleCancel} disabled={cancelling}
            className={`flex-1 flex items-center justify-center gap-1 py-2 ${brutalist ? "bg-[#EF476F] border-2 border-[#111] text-[#111] hover:bg-red-400" : "bg-red-700 hover:bg-red-600 text-white"} rounded-lg text-xs font-bold uppercase tracking-widest transition-colors`}>
            <Square size={13} /> {cancelling ? "…" : "Cancel"}
          </button>
        )}
        {isIdle && !hideUploadButton && (
          <>
            <input ref={fileRef} type="file" accept=".gcode,.gc,.gco"
              className="hidden" onChange={handleUpload} />
            <button onClick={() => fileRef.current?.click()} disabled={uploading}
              className={`flex-1 flex items-center justify-center gap-2 py-2 ${brutalist ? "bg-[#4D90FE] border-2 border-[#111] text-white hover:bg-blue-400" : "bg-blue-600 hover:bg-blue-500 text-white"} rounded-lg text-xs font-bold uppercase tracking-widest transition-colors`}>
              <Upload size={13} /> {uploading ? "Uploading…" : "Upload & Print"}
            </button>
          </>
        )}
      </div>

      {uploadMsg && (
        <div className="text-[10px] text-center font-mono opacity-80 shrink-0">{uploadMsg}</div>
      )}

      <div className="mt-auto pt-2 shrink-0">
        <SpoolPicker />
      </div>
    </div>
  );
}
