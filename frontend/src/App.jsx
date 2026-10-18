import React, { useState, useEffect } from "react";
import { AlertTriangle, X, Bell, WifiOff, BellRing, Layers } from "lucide-react";
import { useStore } from "./store";
import { ProfileBar } from "./ProfileBar";
import { NavRail } from "./NavRail";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { DashboardGrid } from "./DashboardGrid";
import { DigitalTwinPage } from "./DigitalTwinPage";
import { FleetPage } from "./FleetPage";
import { IncidentModal } from "./IncidentModal";
import { FileManager } from "./FileManager";
import { ConfigEditor, HeightmapModal, PowerModal } from "./Modals";
import { SettingsModal } from "./SettingsModal";
import { CalibrationWizard } from "./CalibrationWizard";
import { SpoolManager } from "./SpoolManager";
import { TouchUI } from "./TouchUI";
import { LoginScreen } from "./LoginScreen";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

const originalConsoleWarn = console.warn;
console.warn = (...args) => {
  if (typeof args[0] === "string" && args[0].includes("THREE.Clock")) return;
  originalConsoleWarn(...args);
};




function GlobalDropZone() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadAndPrint = useStore(s => s.uploadAndPrint);

  useEffect(() => {
    let dragCounter = 0;

    const handleDragEnter = (e) => {
      e.preventDefault();
      dragCounter++;
      if (e.dataTransfer.types.includes("Files")) {
        setIsDragging(true);
      }
    };
    const handleDragOver = (e) => {
      e.preventDefault();
    };
    const handleDragLeave = (e) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter === 0) {
        setIsDragging(false);
      }
    };
    const handleDrop = async (e) => {
      e.preventDefault();
      dragCounter = 0;
      setIsDragging(false);

      const file = e.dataTransfer.files[0];
      if (!file) return;
      if (!file.name.toLowerCase().endsWith(".gcode") && !file.name.toLowerCase().endsWith(".bgcode")) {
         window.dispatchEvent(new CustomEvent("indus3d-notification", { detail: "Invalid file type. Please drop a .gcode or .bgcode file." }));
         return;
      }

      const start = window.confirm(`Upload ${file.name}?\nPress OK to upload and START PRINTING immediately, or Cancel to just upload.`);

      setUploading(true);
      try {
         await uploadAndPrint(file, start);
         window.dispatchEvent(new CustomEvent("indus3d-notification", { detail: `Successfully uploaded ${file.name}` }));
      } catch (err) {
         window.dispatchEvent(new CustomEvent("indus3d-notification", { detail: `Upload failed: ${err.message}` }));
      }
      setUploading(false);
    };

    window.addEventListener("dragenter", handleDragEnter);
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("dragleave", handleDragLeave);
    window.addEventListener("drop", handleDrop);

    return () => {
      window.removeEventListener("dragenter", handleDragEnter);
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("drop", handleDrop);
    };
  }, [uploadAndPrint]);

  if (!isDragging && !uploading) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 flex flex-col items-center justify-center pointer-events-none backdrop-blur-sm transition-all duration-300">
      <div className="border-4 border-dashed border-emerald-500 rounded-3xl p-16 flex flex-col items-center justify-center bg-emerald-900/20 max-w-2xl w-full mx-4">
        {uploading ? (
          <>
            <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-emerald-400 mb-6"></div>
            <h2 className="text-4xl font-bold text-white mb-2">Uploading...</h2>
            <p className="text-emerald-300 text-lg">Please wait while the file is sent to Moonraker.</p>
          </>
        ) : (
          <>
            <Layers size={80} className="text-emerald-400 mb-6 animate-bounce" />
            <h2 className="text-4xl font-bold text-white mb-2">Drop G-Code to Print</h2>
            <p className="text-emerald-300 text-lg">Release anywhere on the screen to upload</p>
          </>
        )}
      </div>
    </div>
  );
}

function ToastContainer() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    // Request notification permission on mount
    if (window.Notification && Notification.permission === "default") {
      Notification.requestPermission();
    }

    const onNotification = (e) => {
      const id = Date.now();
      setToasts((prev) => [...prev, { id, msg: e.detail }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    };
    window.addEventListener("indus3d-notification", onNotification);
    return () => window.removeEventListener("indus3d-notification", onNotification);
  }, []);

  if (!toasts.length) return null;
  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map(t => (
        <div key={t.id} className="bg-blue-600/90 text-white px-4 py-3 rounded-lg shadow-xl flex items-center gap-3 text-sm font-medium animate-in slide-in-from-right">
          <BellRing size={16} />
          {t.msg}
        </div>
      ))}
    </div>
  );
}

function ThrottledBadge() {
  const [throttled, setThrottled] = useState(false);

  useEffect(() => {
    let timeout;
    const onThrottle = () => {
      setThrottled(true);
      clearTimeout(timeout);
      timeout = setTimeout(() => setThrottled(false), 5000); // Hide after 5 seconds of no 429s
    };
    window.addEventListener("api-throttled", onThrottle);
    return () => window.removeEventListener("api-throttled", onThrottle);
  }, []);

  if (!throttled) return null;
  return (
    <div className="fixed bottom-4 right-4 bg-yellow-600/90 text-white px-3 py-2 rounded-lg shadow-lg flex items-center gap-2 z-50 text-sm font-medium animate-pulse">
      <WifiOff size={16} /> Connection Throttled (Backing off...)
    </div>
  );
}

// ── Alert Bar ─────────────────────────────────────────────────────────────────
function AlertBar() {
  const alerts       = useStore((s) => s.alerts);
  const dismissAlert = useStore((s) => s.dismissAlert);
  const brutalist = useIsBrutalist();
  if (!alerts.length) return null;
  const colours = {
    critical: "bg-red-600 border-red-500 text-white",
    warn:     "bg-yellow-600 border-yellow-500 text-white",
    info:     "bg-blue-700 border-blue-500 text-white",
  };
  return (
    <div className="flex flex-col gap-1 mb-2 shrink-0">
      {alerts.map((a) => (
        <div key={a.id} className={`flex items-center justify-between px-4 py-2 border text-xs font-bold tracking-wide ${brutalist ? "rounded-none border-2 border-[#111]" : "rounded-lg"} ${colours[a.level] ?? colours.info} ${a.level === "critical" ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2"><AlertTriangle size={14} />{a.msg}</div>
          <button onClick={() => dismissAlert(a.id)} className="ml-4 opacity-70 hover:opacity-100"><X size={13} /></button>
        </div>
      ))}
    </div>
  );
}

// ── Top Header ────────────────────────────────────────────────────────────────

// ── Progress favicon ──────────────────────────────────────────────────────────
let _defaultFaviconHref = null;
function ProgressFavicon() {
  const enabled  = useStore((s) => s.uiPrefs.showProgressFavicon);
  const progress = useStore((s) => s.telemetry?.progress);
  const state    = useStore((s) => s.telemetry?.state);

  useEffect(() => {
    const link = document.querySelector("link[rel~='icon']");
    if (!link) return;
    if (_defaultFaviconHref === null) _defaultFaviconHref = link.href;

    const isPrinting = enabled && state === "printing" && typeof progress === "number";
    if (!isPrinting) {
      link.href = _defaultFaviconHref;
      if (document.title.match(/^\d+% · /)) {
        document.title = document.title.replace(/^\d+% · /, "");
      }
      return;
    }

    const pct = Math.max(0, Math.min(100, Math.round(progress)));
    const size = 64;
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, size, size);
    ctx.lineWidth = 8;
    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 6, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = "#10b981";
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 6, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * pct) / 100);
    ctx.stroke();
    link.href = canvas.toDataURL("image/png");

    const baseTitle = document.title.replace(/^\d+% · /, "");
    document.title = `${pct}% · ${baseTitle}`;
  }, [enabled, progress, state]);

  return null;
}

function TopHeader() {
  const fault   = useStore((s) => s.telemetry?.fault);
  const alerts  = useStore((s) => s.alerts);
  const simMode = useStore((s) => s.simMode);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const powerAction = useStore(s => s.powerAction);

  const handleEstop = async () => {
    if (!window.confirm("Emergency stop the printer? This immediately halts motion and heaters.")) return;
    const result = await powerAction("emergency_stop");
    window.dispatchEvent(new CustomEvent("indus3d-notification", {
      detail: result.error ? `Emergency stop failed: ${result.error}` : "Emergency stop sent",
    }));
  };

  return (
    <header className={`flex justify-between items-center px-4 py-2.5 mb-3 shrink-0 ${t.header}`}>
      <h1 className={`text-xl font-bold ${brutalist ? "font-mono tracking-widest" : soft ? "text-[#7C9B6E] tracking-wide" : "text-blue-500 tracking-widest"}`}>
        INDUS<span className={brutalist ? "" : "opacity-80"}>3D</span>
      </h1>
      <div className="flex gap-3 items-center">
        <button
          onClick={handleEstop}
          className={`flex items-center gap-2 px-4 py-1.5 font-bold transition-colors shadow-sm
            ${brutalist ? "bg-red-600 text-white border-[3px] border-black hover:bg-black"
              : "bg-red-600 text-white rounded-lg hover:bg-red-700"}`}
        >
          <AlertTriangle size={16} />
          E-STOP
        </button>
        {alerts.length > 0 && (
          <div className="flex items-center gap-1 px-3 py-1.5 bg-red-600 text-white rounded-full text-xs font-bold animate-pulse">
            <Bell size={13} />{alerts.length} Alert{alerts.length > 1 ? "s" : ""}
          </div>
        )}
        <ThemeSwitcher />
        <div className={`flex items-center gap-2 px-3 py-1.5 ${t.chip} ${brutalist ? "bg-white" : t.cell}`}>
          <div className={`w-2.5 h-2.5 rounded-full animate-pulse ${fault ? "bg-red-500" : "bg-green-500"}`} />
          <span className="text-[10px] uppercase tracking-widest font-semibold">
            {simMode ? "SIM MODE" : fault ? "SYSTEM FAULT" : "Live"}
          </span>
        </div>
      </div>
    </header>
  );
}

// ── Root App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page,           setPage]          = useState("dashboard");
  const [showEditor,     setShowEditor]    = useState(false);
  const [showHeightmap,  setShowHeightmap] = useState(false);
  const [showSettings,   setShowSettings]  = useState(false);
  const [showCalibration,setShowCalibration] = useState(false);
  const [showPower, setShowPower] = useState(false);
  const [showSpools, setShowSpools] = useState(false);
  const [dismissedIncident, setDismissedIncident] = useState(false);


  const isDarkMode = useStore((s) => s.isDarkMode);
  const telemetryState = useStore((s) => s.telemetry?.state);

  const dashboardMode = useStore((s) => s.dashboardMode);
  const t = useThemeTokens();

  const authStatus        = useStore((s) => s.authStatus);
  const fetchAuthStatus   = useStore((s) => s.fetchAuthStatus);
  const initWebSocket     = useStore((s) => s.initWebSocket);
  const fetchProfile      = useStore((s) => s.fetchProfile);
  const fetchPreferences  = useStore((s) => s.fetchPreferences);
  const fetchSensorData   = useStore((s) => s.fetchSensorData);
  const fetchActionLog    = useStore((s) => s.fetchActionLog);
  const fetchRemoteConfig = useStore((s) => s.fetchRemoteConfig);

  useEffect(() => {
    fetchAuthStatus();
  }, [fetchAuthStatus]);

  useEffect(() => {
    // Don't init telemetry until authenticated (or auth not required)
    if (authStatus.loading || (authStatus.auth_required && !authStatus.authenticated)) return;
    fetchRemoteConfig();
    fetchProfile();
    fetchPreferences();
    initWebSocket();
    fetchSensorData();
    fetchActionLog();
    const iv = setInterval(fetchSensorData, 2000);
    return () => clearInterval(iv);
  }, [authStatus, fetchActionLog, fetchProfile, fetchPreferences, fetchRemoteConfig, fetchSensorData, initWebSocket]);

  // Auth gate — show login screen if auth is required and not authenticated
  if (authStatus.loading) {
    return <div className={`flex items-center justify-center h-screen w-full ${t.page}`}>
      <div className="text-sm opacity-50">Loading…</div>
    </div>;
  }
  const isTouchMode = new URLSearchParams(window.location.search).get("mode") === "touch";
  if (isTouchMode) {
    return <TouchUI />;
  }

  if (authStatus.auth_required && !authStatus.authenticated) {
    return <LoginScreen />;
  }

  return (
    <div className={`flex h-screen w-full font-sans overflow-hidden transition-colors duration-300 ${t.page}`}>
      <NavRail
        page={page}
        setPage={setPage}
        onOpenEditor={() => setShowEditor(true)}
        onOpenHeightmap={() => setShowHeightmap(true)}
        onOpenSettings={() => setShowSettings(true)}
        onOpenCalibration={() => setShowCalibration(true)}
        onOpenPower={() => setShowPower(true)}
        onOpenSpools={() => setShowSpools(true)}
      />
      <div className="flex-1 relative flex flex-col p-4 min-w-0">
        <TopHeader />
        <ProfileBar isDarkMode={isDarkMode} />
        <AlertBar />
        {showEditor    && <ConfigEditor   isDarkMode={isDarkMode} onClose={() => setShowEditor(false)} />}
        {showHeightmap && <HeightmapModal isDarkMode={isDarkMode} onClose={() => setShowHeightmap(false)} />}
        {showSettings  && <SettingsModal onClose={() => setShowSettings(false)} />}
        {showCalibration && <CalibrationWizard onClose={() => setShowCalibration(false)} />}
        {showPower && <PowerModal onClose={() => setShowPower(false)} />}
        {showSpools && <SpoolManager onClose={() => setShowSpools(false)} />}
        {telemetryState === "error" && !dismissedIncident && <IncidentModal onClose={() => setDismissedIncident(true)} />}

        {page === "dashboard" ? <DashboardGrid key={dashboardMode} isDarkMode={isDarkMode} />
          : page === "fleet" ? <FleetPage isDarkMode={isDarkMode} />
          : page === "files" ? <FileManager />
          : <DigitalTwinPage isDarkMode={isDarkMode} />}
      </div>
    </div>
  );
}
// trigger reload 24
