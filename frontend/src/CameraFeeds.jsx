/**
 * CameraFeeds.jsx
 * ----------------
 * Renders all Crowsnest camera streams registered in Moonraker.
 * Automatically discovers cameras via /api/printer/cameras.
 * Supports multiple streams (nozzle cam, chamber cam, wide-view).
 */

import React, { useState, useEffect } from "react";
import { Camera, ChevronLeft, ChevronRight, Maximize2 } from "lucide-react";
import { API } from "./store";
import { useThemeTokens } from "./theme";

export function CameraFeeds({ isDarkMode }) {
  const t = useThemeTokens();
  const [cameras,     setCameras]     = useState([]);
  const [activeIdx,   setActiveIdx]   = useState(0);
  const [fullscreen,  setFullscreen]  = useState(false);
  const [error,       setError]       = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const res  = await fetch(`${API}/api/v1/printer/cameras`);
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          setCameras(data.filter(c => c.enabled !== false));
        }
      } catch {
        setError("Camera list unavailable");
      }
    })();
  }, []);

  const inner = t.panel;

  const activeCam = cameras[activeIdx] ?? null;

  return (
    <div className={`h-full p-4 flex flex-col ${inner}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-gray-400">
          <Camera size={16} />
          <h3 className="font-semibold tracking-wide uppercase text-xs">
            Live Feed
            {cameras.length > 1 && (
              <span className="ml-2 text-[9px] px-1.5 py-0.5 bg-blue-700 text-white rounded-full">
                {cameras.length} cams
              </span>
            )}
          </h3>
        </div>
        {cameras.length > 0 && (
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="p-1 rounded hover:bg-gray-700 transition-colors opacity-60 hover:opacity-100"
          >
            <Maximize2 size={13} />
          </button>
        )}
      </div>

      {/* Camera selector tabs */}
      {cameras.length > 1 && (
        <div className="flex gap-1 mb-2 overflow-x-auto">
          {cameras.map((cam, i) => (
            <button
              key={i}
              onClick={() => setActiveIdx(i)}
              className={`shrink-0 px-2 py-1 rounded text-[9px] font-bold uppercase tracking-widest transition-colors ${
                i === activeIdx
                  ? "bg-blue-600 text-white"
                  : isDarkMode
                  ? "bg-gray-800 text-gray-400 hover:bg-gray-700"
                  : "bg-gray-200 text-gray-600 hover:bg-gray-300"
              }`}
            >
              {cam.name || `CAM ${i + 1}`}
            </button>
          ))}
        </div>
      )}

      {/* Stream */}
      <div
        className={`relative w-full bg-black rounded-lg overflow-hidden border border-gray-800/50 ${
          fullscreen ? "fixed inset-4 z-50" : "aspect-video"
        }`}
      >
        {activeCam ? (
          <>
            <img
              src={activeCam.stream_url}
              alt={activeCam.name || "Live cam"}
              className="absolute inset-0 w-full h-full object-contain"
              onError={(e) => {
                e.target.style.display = "none";
                e.target.nextSibling.style.display = "flex";
              }}
            />
            {/* Fallback shown when img fails */}
            <div
              className="absolute inset-0 hidden items-center justify-center text-[10px] text-gray-500 font-mono"
            >
              <div className="text-center">
                <Camera size={24} className="mx-auto mb-2 opacity-30" />
                <div>Stream unavailable</div>
                <div className="opacity-50 text-[9px] mt-1">{activeCam.stream_url}</div>
              </div>
            </div>

            {/* Camera name overlay */}
            <div className="absolute bottom-2 left-2 px-2 py-0.5 bg-black/60 text-white text-[9px] font-mono rounded">
              {activeCam.name || "CAM"}
            </div>

            {/* Navigation arrows for multiple cameras */}
            {cameras.length > 1 && (
              <>
                <button
                  onClick={() => setActiveIdx((activeIdx - 1 + cameras.length) % cameras.length)}
                  className="absolute left-1 top-1/2 -translate-y-1/2 p-1 bg-black/50 rounded-full text-white hover:bg-black/80"
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  onClick={() => setActiveIdx((activeIdx + 1) % cameras.length)}
                  className="absolute right-1 top-1/2 -translate-y-1/2 p-1 bg-black/50 rounded-full text-white hover:bg-black/80"
                >
                  <ChevronRight size={14} />
                </button>
              </>
            )}

            {/* Close fullscreen */}
            {fullscreen && (
              <button
                onClick={() => setFullscreen(false)}
                className="absolute top-3 right-3 px-3 py-1 bg-black/70 text-white text-xs rounded font-bold"
              >
                ✕ Close
              </button>
            )}
          </>
        ) : error ? (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-gray-500">
            {error}
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-gray-600 font-mono">
            <div className="text-center">
              <Camera size={20} className="mx-auto mb-1 opacity-20" />
              <div>No cameras detected</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
