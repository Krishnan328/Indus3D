import React, { useState } from "react";
import {
  X,
  Upload,
  Layers,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Trash2,
  Plus,
  Box,
  Crosshair,
  FileCode,
} from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";

export function BedSettingsModal({ onClose }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const bed = useStore((s) => s.bed);
  const importOrcaBed = useStore((s) => s.importOrcaBed);
  const uploadBedStl = useStore((s) => s.uploadBedStl);
  const deleteBedStl = useStore((s) => s.deleteBedStl);
  const addCornerScrewsPreset = useStore((s) => s.addCornerScrewsPreset);
  const clearBedExclusions = useStore((s) => s.clearBedExclusions);
  const updateBedConfig = useStore((s) => s.updateBedConfig);

  const [uploading, setUploading] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [testCoords, setTestCoords] = useState({ x: 30, y: 30, z: 2 });
  const [testResult, setTestResult] = useState(null);

  // Manual screw form
  const [screwForm, setScrewForm] = useState({ insetX: 30, insetY: 30, radius: 12 });

  const borderClass = brutalist ? "border-[#111] border-2" : `border ${t.border}`;

  const handleOrcaUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";  // allow re-selecting same file after error
    setUploading(true);
    setFeedback("");
    const res = await importOrcaBed(file);
    setUploading(false);
    if (res.status === "ok") {
      setFeedback(`✅ ${res.message}`);
    } else {
      setFeedback(`❌ ${res.error || "Failed to import OrcaSlicer profile"}`);
    }
  };

  const handleStlUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";  // allow re-selecting same file after error
    setUploading(true);
    setFeedback("");
    const res = await uploadBedStl(file);
    setUploading(false);
    if (res.status === "ok") {
      setFeedback(`✅ ${res.message}`);
    } else {
      setFeedback(`❌ ${res.error || "Failed to upload STL model"}`);
    }
  };

  const handleTestCoordinate = () => {
    const { x, y, z } = testCoords;
    const clearance = bed?.clearance_height_mm ?? 10.0;
    
    // Bounds check
    const inBounds = x >= (bed?.min_x ?? 0) && x <= (bed?.max_x ?? 300) &&
                     y >= (bed?.min_y ?? 0) && y <= (bed?.max_y ?? 300) &&
                     z >= 0 && z <= (bed?.size_z_mm ?? 400);

    // Exclusion check
    let inExcl = false;
    let zoneIdx = null;

    if (z < clearance && bed?.bed_exclude_area) {
      for (let i = 0; i < bed.bed_exclude_area.length; i++) {
        const poly = bed.bed_exclude_area[i];
        if (poly && poly.length >= 3) {
          const xs = poly.map((p) => p[0]);
          const ys = poly.map((p) => p[1]);
          if (x >= Math.min(...xs) && x <= Math.max(...xs) &&
              y >= Math.min(...ys) && y <= Math.max(...ys)) {
            inExcl = true;
            zoneIdx = i;
            break;
          }
        }
      }
    }

    if (!inBounds) {
      setTestResult({ safe: false, reason: "Outside printable bed volume" });
    } else if (inExcl) {
      setTestResult({ safe: false, reason: `Collision risk: inside bed screw zone #${zoneIdx + 1} at low Z` });
    } else {
      setTestResult({ safe: true, reason: "Safe movement path" });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className={`w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden ${t.panel}`}>
        {/* Header */}
        <div className={`flex items-center justify-between p-4 border-b ${t.border}`}>
          <div className="flex items-center gap-2">
            <Layers size={20} className="text-emerald-500" />
            <h2 className="font-bold text-base tracking-wide uppercase">
              Printer Bed Geometry & Collision Safety
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded opacity-60 hover:opacity-100 transition-opacity"
          >
            <X size={18} />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
          {/* Feedback banner */}
          {feedback && (
            <div className={`p-3 rounded text-xs font-mono font-bold ${feedback.startsWith("✅") ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-red-500/20 text-red-400 border border-red-500/30"}`}>
              {feedback}
            </div>
          )}

          {/* Current Bed Overview */}
          <div className={`p-4 rounded-xl ${borderClass} bg-gray-500/5 flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase font-bold tracking-wider opacity-60">Active Bed Dimensions</span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 font-mono">
                Source: {bed?.source_name || "default"}
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
              <div className="p-2 rounded bg-black/20 font-mono">
                <span className="block text-[10px] opacity-50">Width (X)</span>
                <span className="text-sm font-bold text-emerald-400">{bed?.size_x_mm ?? 300} mm</span>
              </div>
              <div className="p-2 rounded bg-black/20 font-mono">
                <span className="block text-[10px] opacity-50">Depth (Y)</span>
                <span className="text-sm font-bold text-emerald-400">{bed?.size_y_mm ?? 300} mm</span>
              </div>
              <div className="p-2 rounded bg-black/20 font-mono">
                <span className="block text-[10px] opacity-50">Height (Z)</span>
                <span className="text-sm font-bold text-emerald-400">{bed?.size_z_mm ?? 400} mm</span>
              </div>
              <div className="p-2 rounded bg-black/20 font-mono">
                <span className="block text-[10px] opacity-50">Origin</span>
                <span className="text-sm font-bold text-blue-400">
                  {bed?.origin_center ? "Center (0,0)" : "Corner (0,0)"}
                </span>
              </div>
            </div>
          </div>

          {/* 1. Slicer & 3D Model Importers */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* OrcaSlicer Profile Import */}
            <div className={`p-4 rounded-xl ${borderClass} flex flex-col justify-between gap-3`}>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <FileCode size={16} className="text-blue-400" />
                  <h3 className="font-bold text-sm">Import OrcaSlicer Profile</h3>
                </div>
                <p className="text-xs opacity-60">
                  Import machine JSON profile (.json) from OrcaSlicer, PrusaSlicer, or Bambu Studio. Automatically configures bed shape, printable height, and screw exclusion areas.
                </p>
              </div>

              <label className="flex items-center justify-center gap-2 px-3 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs cursor-pointer transition-colors mt-2">
                <Upload size={14} />
                <span>{uploading ? "Importing…" : "Upload Orca JSON"}</span>
                <input
                  type="file"
                  accept=".json"
                  onChange={handleOrcaUpload}
                  disabled={uploading}
                  className="hidden"
                />
              </label>
            </div>

            {/* Custom Bed STL Upload */}
            <div className={`p-4 rounded-xl ${borderClass} flex flex-col justify-between gap-3`}>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <Box size={16} className="text-purple-400" />
                  <h3 className="font-bold text-sm">Bed 3D Model (STL)</h3>
                </div>
                <p className="text-xs opacity-60">
                  Upload a 3D STL model of the build plate to render in the Three.js viewport with real screw cutouts and hardware alignment.
                </p>
              </div>

              <div className="flex items-center gap-2 mt-2">
                <label className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs cursor-pointer transition-colors">
                  <Upload size={14} />
                  <span>{uploading ? "Uploading…" : "Upload Bed STL"}</span>
                  <input
                    type="file"
                    accept=".stl"
                    onChange={handleStlUpload}
                    disabled={uploading}
                    className="hidden"
                  />
                </label>
                {bed?.has_custom_model && (
                  <button
                    onClick={deleteBedStl}
                    title="Remove custom STL"
                    className="p-2 rounded bg-red-500/20 text-red-400 hover:bg-red-500 hover:text-white transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 2. Bed Screws & Exclusion Zones Manager */}
          <div className={`p-4 rounded-xl ${borderClass} flex flex-col gap-4`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldCheck size={16} className="text-emerald-400" />
                <h3 className="font-bold text-sm">Bed Screws & Hardware Keepout Zones</h3>
              </div>
              <span className="text-xs opacity-50 font-mono">
                {bed?.bed_exclude_area?.length ?? 0} active zones
              </span>
            </div>

            <p className="text-xs opacity-60">
              When the nozzle drops below <span className="font-bold text-emerald-400">{bed?.clearance_height_mm ?? 10} mm</span>, Indus3D strictly forbids downward Z-offset corrections and warns against any travel moves that could crash into bed screws or bed clips.
            </p>

            {/* Presets & Actions */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => addCornerScrewsPreset(screwForm.insetX, screwForm.insetY, screwForm.radius)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition-colors"
              >
                <Plus size={13} />
                <span>Add 4 Corner Screws Preset</span>
              </button>
              <button
                onClick={clearBedExclusions}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-700 hover:border-red-500 hover:text-red-400 text-xs transition-colors"
              >
                <Trash2 size={13} />
                <span>Clear All Zones</span>
              </button>
            </div>

            {/* List of active exclusion zones */}
            {bed?.bed_exclude_area && bed.bed_exclude_area.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-40 overflow-y-auto">
                {bed.bed_exclude_area.map((poly, idx) => {
                  const xs = poly.map((p) => p[0]);
                  const ys = poly.map((p) => p[1]);
                  const minX = Math.min(...xs);
                  const maxX = Math.max(...xs);
                  const minY = Math.min(...ys);
                  const maxY = Math.max(...ys);

                  return (
                    <div key={idx} className="p-2.5 rounded bg-black/20 border border-gray-800 text-xs font-mono flex items-center justify-between">
                      <div>
                        <span className="font-bold text-red-400">Zone #{idx + 1} (Screw/Clip)</span>
                        <div className="text-[10px] opacity-60">
                          X: {minX.toFixed(1)}–{maxX.toFixed(1)} mm | Y: {minY.toFixed(1)}–{maxY.toFixed(1)} mm
                        </div>
                      </div>
                      <div className="w-2.5 h-2.5 rounded-full bg-red-500"></div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded border border-dashed border-gray-800 text-center text-xs opacity-50 italic">
                No exclusion zones defined. Import from OrcaSlicer or click "Add 4 Corner Screws Preset" to protect leveling screws.
              </div>
            )}
          </div>

          {/* 3. Real-Time Collision Safety Checker */}
          <div className={`p-4 rounded-xl ${borderClass} bg-gray-500/5 flex flex-col gap-3`}>
            <div className="flex items-center gap-2">
              <Crosshair size={16} className="text-yellow-400" />
              <h3 className="font-bold text-sm">Interactive Coordinate Collision Check</h3>
            </div>
            <p className="text-xs opacity-60">
              Test whether a specific toolhead coordinate is safe or if it intersects a leveling screw / hardware keepout zone.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5 font-mono text-xs">
                <span className="opacity-50">X:</span>
                <input
                  type="number"
                  value={testCoords.x}
                  onChange={(e) => setTestCoords({ ...testCoords, x: parseFloat(e.target.value) || 0 })}
                  className="w-16 px-2 py-1 rounded bg-black/30 border border-gray-700 font-mono text-xs"
                />
              </div>
              <div className="flex items-center gap-1.5 font-mono text-xs">
                <span className="opacity-50">Y:</span>
                <input
                  type="number"
                  value={testCoords.y}
                  onChange={(e) => setTestCoords({ ...testCoords, y: parseFloat(e.target.value) || 0 })}
                  className="w-16 px-2 py-1 rounded bg-black/30 border border-gray-700 font-mono text-xs"
                />
              </div>
              <div className="flex items-center gap-1.5 font-mono text-xs">
                <span className="opacity-50">Z:</span>
                <input
                  type="number"
                  value={testCoords.z}
                  onChange={(e) => setTestCoords({ ...testCoords, z: parseFloat(e.target.value) || 0 })}
                  className="w-16 px-2 py-1 rounded bg-black/30 border border-gray-700 font-mono text-xs"
                />
              </div>
              <button
                onClick={handleTestCoordinate}
                className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-white font-bold text-xs transition-colors"
              >
                Validate Point
              </button>

              {testResult && (
                <div className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono font-bold ${testResult.safe ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
                  {testResult.safe ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
                  <span>{testResult.reason}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className={`flex items-center justify-between p-4 border-t ${t.border}`}>
          <span className="text-[10px] opacity-40 font-mono">
            Safety Clearance: Z &lt; {bed?.clearance_height_mm ?? 10}mm
          </span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
