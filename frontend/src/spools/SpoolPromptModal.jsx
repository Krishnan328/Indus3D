import React, { useState } from "react";
import { AlertTriangle, Play, X, Disc3, Check, QrCode } from "lucide-react";
import { useStore } from "../store";
import { useThemeTokens, useIsBrutalist } from "../theme";

export function SpoolPromptModal({ isOpen, onClose, onConfirmPrint, issues = [], filename = "", metadata = {} }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const spools = useStore((s) => s.spools);
  const activeSpoolId = useStore((s) => s.activeSpoolId);
  const setActiveSpool = useStore((s) => s.setActiveSpool);

  const [selectedSpoolId, setSelectedSpoolId] = useState(activeSpoolId);
  const [qrCodeInput, setQrCodeInput] = useState("");
  const [showQrScan, setShowQrScan] = useState(false);

  if (!isOpen) return null;

  const handleApplySpool = async (id) => {
    const numId = Number(id);
    setSelectedSpoolId(numId);
    if (!isNaN(numId)) {
      await setActiveSpool(numId);
    }
  };

  const handleQrLookup = (e) => {
    e.preventDefault();
    const query = qrCodeInput.trim().toLowerCase();
    if (!query) return;

    // Search by ID or lot number or name
    const found = spools.find((s) =>
      String(s.id) === query ||
      (s.lot_number && s.lot_number.toLowerCase().includes(query)) ||
      (s.filament?.name && s.filament.name.toLowerCase().includes(query))
    );

    if (found) {
      handleApplySpool(found.id);
      setShowQrScan(false);
      setQrCodeInput("");
    } else {
      alert(`No spool matching code "${qrCodeInput}" found.`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
      <div className={`max-w-lg w-full p-6 rounded-2xl flex flex-col gap-4 border shadow-2xl ${t.panel}`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5 text-amber-400">
            <AlertTriangle size={22} className="shrink-0" />
            <h3 className="font-bold text-base text-gray-100">Filament Spool Sanity Warning</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded opacity-60 hover:opacity-100 text-gray-400 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>

        {/* Target File details */}
        <div className="p-3 rounded-lg bg-black/40 border border-white/10 font-mono text-xs flex flex-col gap-1">
          <div className="truncate"><span className="opacity-50">File:</span> <strong className="text-white">{filename}</strong></div>
          <div className="flex justify-between">
            <span><span className="opacity-50">Material:</span> {metadata?.filament_type || "Unknown"}</span>
            <span><span className="opacity-50">Required:</span> ~{Math.round(metadata?.filament_weight_total || 0)}g</span>
          </div>
        </div>

        {/* Warning messages */}
        <div className="flex flex-col gap-2">
          {issues.map((issue, idx) => (
            <div
              key={idx}
              className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2.5"
            >
              <AlertTriangle size={15} className="shrink-0 mt-0.5" />
              <span>{issue.message}</span>
            </div>
          ))}
        </div>

        {/* Spool selector / switcher */}
        <div className="flex flex-col gap-1.5 pt-1">
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase font-bold tracking-wider opacity-60 flex items-center gap-1.5">
              <Disc3 size={12} />
              Switch Active Spool
            </label>
            <button
              onClick={() => setShowQrScan(!showQrScan)}
              className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-1"
            >
              <QrCode size={11} />
              {showQrScan ? "Hide QR Input" : "Scan QR / Code"}
            </button>
          </div>

          {showQrScan ? (
            <form onSubmit={handleQrLookup} className="flex gap-2">
              <input
                type="text"
                value={qrCodeInput}
                onChange={(e) => setQrCodeInput(e.target.value)}
                placeholder="Enter Spool ID or Scan QR..."
                className="flex-1 text-xs px-2.5 py-1.5 rounded bg-black/40 border border-white/20 text-white font-mono focus:outline-none focus:border-blue-500"
                autoFocus
              />
              <button
                type="submit"
                className="px-3 py-1.5 rounded text-xs font-bold bg-blue-600 text-white"
              >
                Apply
              </button>
            </form>
          ) : (
            <select
              value={selectedSpoolId ?? ""}
              onChange={(e) => handleApplySpool(e.target.value)}
              className="w-full text-xs px-2.5 py-1.5 rounded bg-black/40 border border-white/20 text-white font-mono focus:outline-none"
            >
              <option value="">No spool selected</option>
              {spools.map((sp) => (
                <option key={sp.id} value={sp.id}>
                  #{sp.id} {sp.filament?.vendor?.name ?? ""} {sp.filament?.name ?? sp.filament?.material ?? `Spool ${sp.id}`} ({Math.round(sp.remaining_weight ?? 0)}g left)
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-white/10">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-semibold hover:bg-white/10 text-gray-300 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirmPrint(filename)}
            className="px-4 py-2 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white flex items-center gap-2 transition-colors"
          >
            <Play size={14} />
            Bypass & Start Print
          </button>
        </div>
      </div>
    </div>
  );
}
