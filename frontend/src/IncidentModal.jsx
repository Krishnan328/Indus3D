import React from "react";
import { AlertOctagon, XCircle, Play, FileText, Wrench } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";

export function IncidentModal({ onClose }) {
  const telemetry = useStore((s) => s.telemetry);
  const alerts = useStore((s) => s.alerts);
  const t = useThemeTokens();

  // Find the root cause from the alerts (critical alerts)
  const criticalAlerts = alerts.filter(a => a.level === "critical" || a.level === "error");
  const rootCause = criticalAlerts.length > 0 
    ? criticalAlerts[0].msg 
    : "Unknown firmware halt or communication timeout.";

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in zoom-in-95 duration-200">
      <div className={`w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl ${t.panel} ring-2 ring-red-500/50`}>
        
        {/* Header */}
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-5 flex justify-between items-start">
          <div className="flex gap-4">
            <div className="p-3 bg-red-500/20 text-red-500 rounded-full shrink-0 animate-pulse">
              <AlertOctagon size={32} strokeWidth={2.5} />
            </div>
            <div>
              <h2 className="text-xl font-bold text-red-500 tracking-tight">Print Halted</h2>
              <p className="text-sm opacity-80 text-red-400 mt-1">Automatic safety shutdown triggered.</p>
            </div>
          </div>
          <button onClick={onClose} className="opacity-50 hover:opacity-100"><XCircle size={24} /></button>
        </div>
        
        {/* Body */}
        <div className="p-6 space-y-6">
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-bold uppercase tracking-widest opacity-50">Root Cause Diagnostics</span>
            <div className="bg-red-500/5 border-l-4 border-red-500 p-4 rounded-r-lg font-mono text-sm text-red-300">
              {rootCause}
            </div>
          </div>
          
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-bold uppercase tracking-widest opacity-50">Context</span>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className={`p-3 rounded ${t.cell}`}>
                <span className="opacity-50 block mb-1">FILE</span>
                <span className="truncate block">{telemetry?.filename || "Unknown"}</span>
              </div>
              <div className={`p-3 rounded ${t.cell}`}>
                <span className="opacity-50 block mb-1">PROGRESS</span>
                <span className="font-bold text-lg">{(telemetry?.progress * 100).toFixed(1)}%</span>
              </div>
            </div>
          </div>
        </div>
        
        {/* Actions */}
        <div className={`p-4 border-t ${t.border} bg-black/20 flex gap-3`}>
          <button 
            onClick={() => {
              onClose();
              // In a real app, this would trigger navigation to the Twin tab and start replay
              // We'll just dispatch an event to switch tabs if the user implements it.
              useStore.getState().fetchReplaySnapshots(500).then(() => useStore.getState().startReplay());
              window.dispatchEvent(new CustomEvent("nav-to-twin-replay"));
            }} 
            className="flex-1 py-3 px-4 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold flex items-center justify-center gap-2 transition-colors"
          >
            <Play size={18} />
            View Incident Playback
          </button>
          
          <button onClick={onClose} className={`py-3 px-6 rounded-xl font-bold flex items-center gap-2 ${t.btn}`}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
