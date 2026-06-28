/**
 * ActionLog.jsx
 * --------------
 * Displays the history of automated corrective actions taken by Indus3D
 * during a print — what alert triggered it, what G-code was sent, when.
 * Goes in the Digital Twin tab below the maintenance panel.
 */

import React from "react";
import { Zap, CheckCircle, XCircle, Clock } from "lucide-react";
import { useStore } from "./store";

const formatTs = (ts) => {
  const d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
  return d.toLocaleTimeString();
};

export function ActionLog({ isDarkMode }) {
  const actionLog          = useStore((s) => s.actionLog);
  const executeAlertAction = useStore((s) => s.executeAlertAction);
  const alerts             = useStore((s) => s.alerts);

  const inner = isDarkMode
    ? "bg-gray-950 border-gray-800/80"
    : "bg-gray-50 border-gray-200";

  return (
    <div className={`p-4 rounded-xl border flex flex-col gap-3 ${inner}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-green-400">
          <Zap size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-sm">
            Corrective Actions
          </h3>
        </div>
        {actionLog.length > 0 && (
          <span className={`text-[9px] font-mono opacity-50`}>
            {actionLog.length} action{actionLog.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Manual trigger buttons for active alerts */}
      {alerts.filter((a) => a.level === "warn").length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-widest opacity-50 mb-1">
            Manual override
          </span>
          {alerts
            .filter((a) => a.level === "warn")
            .map((a) => (
              <button
                key={a.id}
                onClick={() => executeAlertAction(a.id)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[10px] font-bold
                  uppercase tracking-widest transition-colors text-left
                  ${isDarkMode
                    ? "bg-yellow-900/30 border border-yellow-700/50 text-yellow-300 hover:bg-yellow-800/40"
                    : "bg-yellow-50 border border-yellow-200 text-yellow-700 hover:bg-yellow-100"}`}
              >
                <Zap size={11} />
                Apply fix: {a.msg}
              </button>
            ))}
        </div>
      )}

      {/* Log entries */}
      {actionLog.length === 0 ? (
        <div className="text-[11px] opacity-40 italic text-center py-3">
          No actions taken yet
        </div>
      ) : (
        <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
          {actionLog.map((entry, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 px-3 py-2 rounded-lg text-[10px] font-mono
                ${isDarkMode
                  ? "bg-gray-900 border border-gray-800"
                  : "bg-white border border-gray-200 shadow-sm"}`}
            >
              {entry.status === "executed" ? (
                <CheckCircle size={11} className="text-green-400 mt-0.5 shrink-0" />
              ) : (
                <XCircle size={11} className="text-red-400 mt-0.5 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <div className={`truncate ${isDarkMode ? "text-gray-200" : "text-gray-700"}`}>
                  {entry.description}
                </div>
                <div className="flex items-center gap-2 mt-0.5 opacity-50">
                  <span className="font-bold">{entry.gcode}</span>
                  <Clock size={8} />
                  <span>{formatTs(entry.ts ?? entry.timestamp)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
