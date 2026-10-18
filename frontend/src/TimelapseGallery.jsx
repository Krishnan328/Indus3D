import React, { useEffect } from "react";
import { Film, Download, Circle } from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens } from "./theme";

function formatBytes(n) {
  if (!n) return "0 KB";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(unixSeconds) {
  if (!unixSeconds) return "";
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ── Timelapse gallery ─────────────────────────────────────────────────────────
// Browsing past results, same spirit as AnalyticsCard's print history — this
// is a "look at what happened" surface, not a live glance, hence it lives on
// the Digital Twin page rather than the compact dashboard.
export function TimelapseGallery() {
  const timelapses      = useStore((s) => s.timelapses);
  const status          = useStore((s) => s.timelapseStatus);
  const fetchTimelapses = useStore((s) => s.fetchTimelapses);
  const fetchStatus     = useStore((s) => s.fetchTimelapseStatus);
  const t = useThemeTokens();

  useEffect(() => {
    fetchTimelapses();
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus, fetchTimelapses]);

  return (
    <div className={`p-4 ${t.panel}`}>
      <div className="flex items-center gap-2 mb-3 text-pink-400">
        <Film size={16} />
        <h3 className={t.heading}>Timelapse</h3>
        {status.active && (
          <span className="ml-auto flex items-center gap-1.5 px-2 py-0.5 bg-red-600 text-white text-[9px] font-bold rounded-full">
            <Circle size={7} className="animate-pulse fill-white" />
            Recording — {status.frame_count} frames
          </span>
        )}
      </div>

      {!timelapses.length
        ? <div className="text-[11px] opacity-40 italic text-center py-3">
            No completed timelapses yet. Enable it from Settings → Timelapse.
          </div>
        : <div className="flex flex-col gap-1.5">
            {timelapses.map((tl) => (
              <div key={tl.id} className={`flex items-center justify-between px-3 py-2 text-xs ${t.cell}`}>
                <div className="min-w-0">
                  <div className="truncate font-mono">{tl.id}</div>
                  <div className="opacity-50 text-[10px]">{formatWhen(tl.created)} · {formatBytes(tl.size_bytes)}</div>
                </div>
                <a
                  href={`${API}/api/v1/twin/timelapse/${tl.id}/video`}
                  download
                  className={`shrink-0 p-1.5 ml-2 opacity-70 hover:opacity-100 ${t.chip}`}
                  title="Download"
                >
                  <Download size={13} />
                </a>
              </div>
            ))}
          </div>
      }
    </div>
  );
}
