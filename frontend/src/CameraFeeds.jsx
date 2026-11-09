/**
 * CameraFeeds.jsx
 * ----------------
 * Full Multi-Camera Stream Engine with Mainsail/Fluidd feature parity:
 * - Protocol Support: MJPEG, Adaptive MJPEG, WebRTC, HLS (.m3u8), and iFrame.
 * - Aspect Ratios: 16:9, 4:3, 1:1, fill.
 * - Hardware transforms: 0°/90°/180°/270° rotation, horizontal & vertical flip.
 * - Multi-view: Single camera tabs or simultaneous Multi-Camera Grid layout.
 * - Actions: Snapshot capture, Fullscreen toggle, Stream reload, and Camera settings dialog.
 */

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Camera, ChevronLeft, ChevronRight, Maximize2, Minimize2,
  LayoutGrid, Sliders, Settings, RefreshCw, Download, Plus, Trash2, X, Check
} from "lucide-react";
import { API } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";
import {
  detectStreamType,
  STREAM_TYPES,
  buildTransformStyle,
  getAspectRatioStyle,
  ASPECT_RATIOS,
  mergeCameras,
  loadUserCameras,
  saveUserCameras
} from "./camera/cameraLogic";

function SingleCameraStream({ cam, fullscreen, onSnapshot, isDarkMode }) {
  const [loadError, setLoadError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [adaptiveSrc, setAdaptiveSrc] = useState(cam.snapshot_url || cam.stream_url);

  const streamType = cam.service || detectStreamType(cam.stream_url);
  const transform = buildTransformStyle(cam.rotation, cam.flip_h, cam.flip_v);
  const aspectStyle = fullscreen ? { aspectRatio: "auto" } : { aspectRatio: getAspectRatioStyle(cam.aspect_ratio) };

  // Adaptive MJPEG polling
  useEffect(() => {
    if (streamType !== STREAM_TYPES.MJPEG_ADAPTIVE) return;
    const intervalMs = Math.max(100, Math.round(1000 / (cam.target_fps || 5)));
    const iv = setInterval(() => {
      const base = cam.snapshot_url || cam.stream_url;
      const sep = base.includes("?") ? "&" : "?";
      setAdaptiveSrc(`${base}${sep}_t=${Date.now()}`);
    }, intervalMs);
    return () => clearInterval(iv);
  }, [streamType, cam.snapshot_url, cam.stream_url, cam.target_fps]);

  return (
    <div
      className={`relative w-full bg-black rounded-lg overflow-hidden border border-gray-800/60 flex items-center justify-center ${
        fullscreen ? "fixed inset-4 z-50 shadow-2xl" : ""
      }`}
      style={aspectStyle}
    >
      {loadError ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-[10px] text-gray-500 font-mono p-4 text-center">
          <Camera size={24} className="mb-2 opacity-30 text-red-400" />
          <div className="text-gray-300 font-bold mb-1">Stream Unavailable</div>
          <div className="opacity-50 text-[9px] max-w-xs truncate mb-2">{cam.stream_url}</div>
          <button
            onClick={() => { setLoadError(false); setReloadKey((k) => k + 1); }}
            className="px-2.5 py-1 text-[9px] rounded bg-white/10 hover:bg-white/20 text-gray-200 flex items-center gap-1"
          >
            <RefreshCw size={10} /> Retry
          </button>
        </div>
      ) : streamType === STREAM_TYPES.IFRAME ? (
        <iframe
          key={reloadKey}
          src={cam.stream_url}
          title={cam.name}
          className="absolute inset-0 w-full h-full border-0"
          style={{ transform }}
          onError={() => setLoadError(true)}
        />
      ) : streamType === STREAM_TYPES.WEBRTC || streamType === STREAM_TYPES.HLS ? (
        <video
          key={reloadKey}
          src={cam.stream_url}
          autoPlay
          playsInline
          muted
          controls={false}
          className="absolute inset-0 w-full h-full object-contain"
          style={{ transform }}
          onError={() => setLoadError(true)}
        />
      ) : streamType === STREAM_TYPES.MJPEG_ADAPTIVE ? (
        <img
          key={reloadKey}
          src={adaptiveSrc}
          alt={cam.name}
          className="absolute inset-0 w-full h-full object-contain transition-transform"
          style={{ transform }}
          onError={() => setLoadError(true)}
        />
      ) : (
        <img
          key={reloadKey}
          src={`${cam.stream_url}${cam.stream_url.includes("?") ? "&" : "?"}_rk=${reloadKey}`}
          alt={cam.name}
          crossOrigin="anonymous"
          className="absolute inset-0 w-full h-full object-contain transition-transform"
          style={{ transform }}
          onError={() => setLoadError(true)}
        />
      )}

      {/* Camera Name & Protocol Badge */}
      <div className="absolute bottom-2 left-2 flex items-center gap-1.5 pointer-events-none">
        <span className="px-2 py-0.5 bg-black/75 backdrop-blur-sm text-white text-[9px] font-mono rounded font-bold">
          {cam.name || "CAM"}
        </span>
        <span className="px-1.5 py-0.5 bg-blue-900/60 text-blue-300 text-[8px] font-mono rounded uppercase">
          {streamType}
        </span>
      </div>

      {/* Quick Action Overlay (Snapshot, Refresh) */}
      <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 hover:opacity-100 transition-opacity bg-black/60 backdrop-blur-sm p-1 rounded-lg">
        <button
          onClick={() => onSnapshot(cam)}
          title="Take Snapshot"
          className="p-1 text-gray-200 hover:text-white hover:bg-white/10 rounded transition-colors"
        >
          <Download size={12} />
        </button>
        <button
          onClick={() => { setLoadError(false); setReloadKey((k) => k + 1); }}
          title="Reload Stream"
          className="p-1 text-gray-200 hover:text-white hover:bg-white/10 rounded transition-colors"
        >
          <RefreshCw size={12} />
        </button>
      </div>
    </div>
  );
}

export function CameraFeeds({ isDarkMode }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const [discoveredCameras, setDiscoveredCameras] = useState([]);
  const [customCameras, setCustomCameras] = useState([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [isGridView, setIsGridView] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [error, setError] = useState(null);

  // Settings form state
  const [editingCam, setEditingCam] = useState(null);

  const fetchDiscovered = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/cameras`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setDiscoveredCameras(data);
      }
    } catch {
      setError("Camera discovery failed");
    }
  }, []);

  useEffect(() => {
    fetchDiscovered();
    setCustomCameras(loadUserCameras());
  }, [fetchDiscovered]);

  const cameras = mergeCameras(discoveredCameras, customCameras);
  const activeCam = cameras[activeIdx] ?? cameras[0] ?? null;

  const handleSnapshot = (cam) => {
    const url = cam.snapshot_url || cam.stream_url;
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${cam.name || "camera"}_snapshot_${Date.now()}.jpg`;
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleSaveCamera = (e) => {
    e.preventDefault();
    if (!editingCam) return;

    let updated;
    const exists = customCameras.some((c) => c.id === editingCam.id);
    if (exists) {
      updated = customCameras.map((c) => (c.id === editingCam.id ? editingCam : c));
    } else {
      updated = [...customCameras, { ...editingCam, id: editingCam.id || `custom_${Date.now()}` }];
    }
    setCustomCameras(updated);
    saveUserCameras(updated);
    setEditingCam(null);
  };

  const handleDeleteCamera = (id) => {
    const updated = customCameras.filter((c) => c.id !== id);
    setCustomCameras(updated);
    saveUserCameras(updated);
    if (editingCam?.id === id) setEditingCam(null);
  };

  return (
    <div className={`h-full p-4 flex flex-col justify-between ${t.panel}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2 shrink-0">
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

        <div className="flex items-center gap-1">
          {cameras.length > 1 && (
            <button
              onClick={() => setIsGridView(!isGridView)}
              className={`p-1.5 rounded transition-colors ${
                isGridView ? "bg-blue-600 text-white" : "hover:bg-white/10 text-gray-400 hover:text-white"
              }`}
              title={isGridView ? "Switch to Single Cam Tabs" : "Switch to Multi-Cam Grid"}
            >
              <LayoutGrid size={13} />
            </button>
          )}

          <button
            onClick={() => {
              setEditingCam(activeCam ? { ...activeCam } : {
                id: `cam_${Date.now()}`,
                name: "New Camera",
                stream_url: "http://",
                snapshot_url: "",
                service: STREAM_TYPES.MJPEG,
                aspect_ratio: ASPECT_RATIOS.WIDE,
                rotation: 0,
                flip_h: false,
                flip_v: false,
                target_fps: 15,
                enabled: true,
              });
              setShowSettings(true);
            }}
            className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
            title="Configure Cameras"
          >
            <Settings size={13} />
          </button>

          {cameras.length > 0 && (
            <button
              onClick={() => setFullscreen(!fullscreen)}
              className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
              title="Fullscreen Mode"
            >
              {fullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
            </button>
          )}
        </div>
      </div>

      {/* Camera Tabs (Single View Mode) */}
      {!isGridView && cameras.length > 1 && (
        <div className="flex gap-1 mb-2 overflow-x-auto shrink-0 pb-1">
          {cameras.map((cam, i) => (
            <button
              key={cam.id || i}
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

      {/* Main Stream Area */}
      <div className="flex-1 min-h-0 flex flex-col justify-center">
        {cameras.length === 0 ? (
          <div className="w-full h-48 rounded-lg border border-gray-800/50 flex flex-col items-center justify-center text-xs opacity-50 font-mono">
            <Camera size={24} className="mb-2 opacity-30" />
            <div>No cameras detected</div>
            <button
              onClick={() => {
                setEditingCam({
                  id: `cam_${Date.now()}`,
                  name: "Camera 1",
                  stream_url: "http://",
                  snapshot_url: "",
                  service: STREAM_TYPES.MJPEG,
                  aspect_ratio: ASPECT_RATIOS.WIDE,
                  rotation: 0,
                  flip_h: false,
                  flip_v: false,
                  target_fps: 15,
                  enabled: true,
                });
                setShowSettings(true);
              }}
              className="mt-2 px-3 py-1 text-[10px] rounded bg-blue-600 text-white font-sans font-bold"
            >
              + Add Camera
            </button>
          </div>
        ) : isGridView ? (
          /* Grid View Mode */
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 overflow-y-auto max-h-full">
            {cameras.map((cam) => (
              <SingleCameraStream
                key={cam.id}
                cam={cam}
                fullscreen={false}
                onSnapshot={handleSnapshot}
                isDarkMode={isDarkMode}
              />
            ))}
          </div>
        ) : (
          /* Single Camera View */
          <div className="relative">
            <SingleCameraStream
              cam={activeCam}
              fullscreen={fullscreen}
              onSnapshot={handleSnapshot}
              isDarkMode={isDarkMode}
            />

            {/* Left/Right Chevrons for Quick Switching */}
            {cameras.length > 1 && !fullscreen && (
              <>
                <button
                  onClick={() => setActiveIdx((activeIdx - 1 + cameras.length) % cameras.length)}
                  className="absolute left-1 top-1/2 -translate-y-1/2 p-1 bg-black/60 rounded-full text-white hover:bg-black/90 transition-colors"
                  title="Previous Camera"
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  onClick={() => setActiveIdx((activeIdx + 1) % cameras.length)}
                  className="absolute right-1 top-1/2 -translate-y-1/2 p-1 bg-black/60 rounded-full text-white hover:bg-black/90 transition-colors"
                  title="Next Camera"
                >
                  <ChevronRight size={14} />
                </button>
              </>
            )}

            {/* Close fullscreen button */}
            {fullscreen && (
              <button
                onClick={() => setFullscreen(false)}
                className="fixed top-6 right-6 z-50 px-3 py-1.5 bg-black/80 hover:bg-black text-white text-xs rounded-lg font-bold shadow-xl border border-white/20 flex items-center gap-1"
              >
                <Minimize2 size={13} /> Exit Fullscreen
              </button>
            )}
          </div>
        )}
      </div>

      {/* Camera Settings / Add Modal */}
      {showSettings && editingCam && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className={`max-w-md w-full p-6 rounded-2xl flex flex-col gap-4 border shadow-2xl ${t.panel}`}>
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-sm text-gray-100 flex items-center gap-2">
                <Settings size={16} className="text-blue-400" />
                Camera Configuration
              </h3>
              <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-white">
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSaveCamera} className="flex flex-col gap-3 text-xs">
              <div>
                <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Camera Name</label>
                <input
                  type="text"
                  value={editingCam.name || ""}
                  onChange={(e) => setEditingCam({ ...editingCam, name: e.target.value })}
                  className="w-full px-2.5 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                  required
                />
              </div>

              <div>
                <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Stream Protocol / Service</label>
                <select
                  value={editingCam.service || STREAM_TYPES.MJPEG}
                  onChange={(e) => setEditingCam({ ...editingCam, service: e.target.value })}
                  className="w-full px-2.5 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                >
                  <option value={STREAM_TYPES.MJPEG}>MJPEG Stream</option>
                  <option value={STREAM_TYPES.MJPEG_ADAPTIVE}>MJPEG Adaptive (Snapshot Polling)</option>
                  <option value={STREAM_TYPES.WEBRTC}>WebRTC (go2rtc / Janus / WHEP)</option>
                  <option value={STREAM_TYPES.HLS}>HLS (.m3u8)</option>
                  <option value={STREAM_TYPES.IFRAME}>Embedded HTTP / iFrame</option>
                </select>
              </div>

              <div>
                <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Stream URL</label>
                <input
                  type="text"
                  value={editingCam.stream_url || ""}
                  onChange={(e) => setEditingCam({ ...editingCam, stream_url: e.target.value })}
                  placeholder="http://host:8080/stream"
                  className="w-full px-2.5 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                  required
                />
              </div>

              <div>
                <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Snapshot URL (Optional)</label>
                <input
                  type="text"
                  value={editingCam.snapshot_url || ""}
                  onChange={(e) => setEditingCam({ ...editingCam, snapshot_url: e.target.value })}
                  placeholder="http://host:8080/snapshot"
                  className="w-full px-2.5 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Aspect Ratio</label>
                  <select
                    value={editingCam.aspect_ratio || ASPECT_RATIOS.WIDE}
                    onChange={(e) => setEditingCam({ ...editingCam, aspect_ratio: e.target.value })}
                    className="w-full px-2 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                  >
                    <option value={ASPECT_RATIOS.WIDE}>16:9 (Widescreen)</option>
                    <option value={ASPECT_RATIOS.STANDARD}>4:3 (Standard)</option>
                    <option value={ASPECT_RATIOS.SQUARE}>1:1 (Square)</option>
                    <option value={ASPECT_RATIOS.FILL}>Fill / Stretch</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[10px] uppercase font-bold opacity-60 mb-1">Rotation</label>
                  <select
                    value={editingCam.rotation || 0}
                    onChange={(e) => setEditingCam({ ...editingCam, rotation: Number(e.target.value) })}
                    className="w-full px-2 py-1.5 rounded bg-black/40 border border-white/10 text-white font-mono"
                  >
                    <option value={0}>0°</option>
                    <option value={90}>90°</option>
                    <option value={180}>180°</option>
                    <option value={270}>270°</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center gap-4 py-1">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(editingCam.flip_h)}
                    onChange={(e) => setEditingCam({ ...editingCam, flip_h: e.target.checked })}
                    className="rounded"
                  />
                  <span>Flip Horizontal</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(editingCam.flip_v)}
                    onChange={(e) => setEditingCam({ ...editingCam, flip_v: e.target.checked })}
                    className="rounded"
                  />
                  <span>Flip Vertical</span>
                </label>
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-white/10">
                {editingCam.isCustom ? (
                  <button
                    type="button"
                    onClick={() => handleDeleteCamera(editingCam.id)}
                    className="text-red-400 hover:text-red-300 flex items-center gap-1 text-xs"
                  >
                    <Trash2 size={13} /> Delete
                  </button>
                ) : <span />}

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowSettings(false)}
                    className="px-3 py-1.5 rounded hover:bg-white/10 text-gray-300"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold flex items-center gap-1"
                  >
                    <Check size={14} /> Save
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
