import React, { useState, useEffect } from "react";
import { useStore, API } from "./store";
import { useThemeTokens } from "./theme";
import { Maximize2, Pause, Play, Square, AlertTriangle, CheckCircle2, X, Check, Wifi, WifiOff } from "lucide-react";

function PrinterCard({ printer, isLive, onQuickView }) {
  const t = useThemeTokens();
  
  // Use live data if it's the current printer, otherwise use simulated data
  const telemetry = useStore((s) => s.telemetry);
  const pausePrint = useStore((s) => s.pausePrint);
  const resumePrint = useStore((s) => s.resumePrint);
  const cancelPrint = useStore((s) => s.cancelPrint);
    
  const pName = isLive ? printer.name : printer.name;
  const pStatus = isLive ? telemetry.state : printer.status;
  const pProg = isLive ? telemetry.progress : printer.progress;
  const pFile = isLive ? telemetry.filename : printer.filename;
  
  const isError = pStatus === "error" || pStatus === "halted";
  const isPrinting = pStatus === "printing";
  const isPaused = pStatus === "paused";
  
  return (
    <div className={`flex flex-col overflow-hidden ${t.panel} ${isError ? "ring-2 ring-red-500" : ""}`}>
      {/* Header */}
      <div className={`px-3 py-2 flex justify-between items-center border-b ${t.border}`}>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isPrinting ? "bg-emerald-500 animate-pulse" : isError ? "bg-red-500" : "bg-gray-400"}`} />
          <span className="font-bold text-sm tracking-wide">{pName}</span>
        </div>
        <button onClick={onQuickView} className="p-1 opacity-50 hover:opacity-100 hover:text-emerald-500 transition-colors">
          <Maximize2 size={14} />
        </button>
      </div>
      
      {/* Webcam / Body */}
      <div className="relative aspect-video bg-black/80 flex items-center justify-center overflow-hidden">
        {isLive ? (
          <img src={`${API}/api/v1/camera/stream`} className="w-full h-full object-cover opacity-80" alt="Live stream" />
        ) : (
          <div className="text-xs opacity-30 font-mono flex flex-col items-center gap-2">
            {isError ? <AlertTriangle size={24} className="text-red-500" /> : <CheckCircle2 size={24} />}
            {isError ? "Camera Offline" : "Simulated Stream"}
          </div>
        )}
        
        {/* Transparent Overlay Stats */}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
          <div className="flex justify-between items-end text-white text-xs font-mono">
            <div className="flex flex-col">
              <span className="opacity-80 truncate w-32">{pFile || "No file"}</span>
              <span className={isError ? "text-red-400 font-bold uppercase" : "text-emerald-400 capitalize"}>{pStatus}</span>
            </div>
            {isPrinting && <span className="text-lg font-bold">{(pProg * 100).toFixed(0)}%</span>}
          </div>
        </div>
      </div>
      
      {/* Controls & Progress */}
      {(isPrinting || isPaused) && (
        <div className="p-3">
          <div className="w-full bg-black/20 h-1.5 rounded-full overflow-hidden mb-3">
            <div className="h-full bg-emerald-500 transition-all duration-500" style={{ width: `${pProg * 100}%` }} />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => isLive && (isPaused ? resumePrint() : pausePrint())}
              disabled={!isLive}
              className={`flex-1 py-1.5 flex justify-center items-center rounded ${t.btn} disabled:opacity-40`}
            >
              {isPaused ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button
              onClick={() => { if (isLive && window.confirm("Cancel the current print?")) cancelPrint(); }}
              disabled={!isLive}
              className={`flex-1 py-1.5 flex justify-center items-center rounded ${t.btn} text-red-400 hover:text-red-300 disabled:opacity-40`}
            >
              <Square size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Fullscreen Mobile-First Quick View
function QuickViewModal({ printer, isLive, onClose }) {
  const telemetry = useStore((s) => s.telemetry);
    
  const pName = isLive ? "Alpha (Local)" : printer.name;
  const pStatus = isLive ? telemetry.state : printer.status;
  const pProg = isLive ? telemetry.progress : printer.progress;
  const pFile = isLive ? telemetry.filename : printer.filename;
  const tTemp = isLive ? telemetry.extTemp : printer.extTemp;
  const bTemp = isLive ? telemetry.bedTemp : printer.bedTemp;

  return (
    <div className="fixed inset-0 z-[300] bg-black flex flex-col animate-in fade-in zoom-in-95 duration-200">
      {/* Fullscreen Video Background */}
      {isLive ? (
        <img src={`${API}/api/v1/camera/stream`} className="absolute inset-0 w-full h-full object-cover opacity-60" alt="Live stream" />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center opacity-20">
          <AlertTriangle size={64} />
        </div>
      )}
      
      {/* Overlay UI */}
      <div className="relative z-10 flex-1 flex flex-col p-6">
        <header className="flex justify-between items-start">
          <div className="flex flex-col drop-shadow-md">
            <h1 className="text-3xl font-bold text-white tracking-tight">{pName}</h1>
            <span className="text-emerald-400 font-mono capitalize">{pStatus}</span>
          </div>
          <button onClick={onClose} className="p-2 bg-black/40 hover:bg-black/60 rounded-full text-white backdrop-blur-md transition-colors">
            <X size={24} />
          </button>
        </header>
        
        <div className="flex-1" />
        
        <footer className="bg-black/40 backdrop-blur-md border border-white/10 rounded-2xl p-5 drop-shadow-xl space-y-4">
          <div className="flex justify-between items-end">
            <div className="flex flex-col text-white font-mono">
              <span className="text-sm opacity-60">PRINTING</span>
              <span className="text-lg font-bold truncate max-w-[200px]">{pFile || "None"}</span>
            </div>
            <div className="text-4xl font-bold text-emerald-400 font-mono">
              {(pProg * 100).toFixed(0)}%
            </div>
          </div>
          
          <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-500 transition-all duration-500" style={{ width: `${pProg * 100}%` }} />
          </div>
          
          <div className="grid grid-cols-2 gap-4 text-white font-mono text-sm pt-2">
            <div className="flex flex-col bg-black/20 p-2 rounded-lg text-center">
              <span className="opacity-50 text-[10px]">NOZZLE</span>
              <span className="text-orange-400 font-bold text-lg">{tTemp}°C</span>
            </div>
            <div className="flex flex-col bg-black/20 p-2 rounded-lg text-center">
              <span className="opacity-50 text-[10px]">BED</span>
              <span className="text-blue-400 font-bold text-lg">{bTemp}°C</span>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}

// A registered-but-not-active printer: no telemetry to show (Indus3D only
// maintains one live connection — see workers/manager.py), so this card
// just offers the switch instead of fabricating status/progress for it.
function InactivePrinterCard({ printer, onActivate, busy }) {
  const t = useThemeTokens();
  return (
    <div className={`flex flex-col overflow-hidden ${t.panel} opacity-80`}>
      <div className={`px-3 py-2 flex justify-between items-center border-b ${t.border}`}>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-gray-400" />
          <span className="font-bold text-sm tracking-wide">{printer.name}</span>
        </div>
      </div>
      <div className="aspect-video bg-black/80 flex flex-col items-center justify-center gap-2 text-xs opacity-40 font-mono">
        <WifiOff size={22} />
        Not connected
        <span className="opacity-60">{printer.host}:{printer.port}</span>
      </div>
      <div className="p-3">
        <button
          onClick={onActivate}
          disabled={busy}
          className={`w-full flex items-center justify-center gap-1.5 py-2 rounded text-xs font-bold transition-all ${t.btn} disabled:opacity-40`}
        >
          <Check size={14} /> {busy ? "Switching…" : "Activate"}
        </button>
      </div>
    </div>
  );
}

export function FleetPage() {
  const t = useThemeTokens();
  const [quickViewPrinter, setQuickViewPrinter] = useState(null);
  const [switchingId, setSwitchingId] = useState(null);
  const [error, setError] = useState("");

  const data = useStore((s) => s.printerInstances);
  const fetchInstances = useStore((s) => s.fetchPrinterInstances);
  const activateInstance = useStore((s) => s.activatePrinterInstance);

  useEffect(() => { fetchInstances(); }, [fetchInstances]);

  // Indus3D maintains one live Moonraker connection at a time and switches
  // between registered printers rather than connecting to several at once
  // (see config/printers.py / workers/manager.py) — this mirrors how
  // Mainsail's own multi-printer support works, it isn't a simultaneous
  // multi-connection dashboard.
  const activePrinter = data.printers.find((p) => p.id === data.active) || { id: data.active, name: "Printer" };
  const inactivePrinters = data.printers.filter((p) => p.id !== data.active);

  const handleActivate = async (id) => {
    setSwitchingId(id);
    setError("");
    const result = await activateInstance(id);
    if (result.error) setError(result.error);
    setSwitchingId(null);
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 flex flex-col">
      <div className="flex justify-between items-end mb-4">
        <div>
          <h1 className={`text-2xl font-black tracking-tight ${t.heading}`}>Fleet Command</h1>
          <p className="text-xs opacity-60 mt-1">One live connection at a time — activate a printer below to switch to it, or add more in Settings → Printers.</p>
        </div>
        <div className="text-xs font-mono opacity-50 bg-black/10 px-3 py-1 rounded-full flex items-center gap-1.5">
          <Wifi size={12} /> {data.printers.length} Registered
        </div>
      </div>

      {error && <div className="mb-4 p-3 text-xs text-red-500 rounded-lg bg-red-500/10">{error}</div>}
      
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-10">
        <PrinterCard key={activePrinter.id} printer={activePrinter} isLive={true} onQuickView={() => setQuickViewPrinter(activePrinter)} />
        {inactivePrinters.map((p) => (
          <InactivePrinterCard key={p.id} printer={p} busy={switchingId === p.id} onActivate={() => handleActivate(p.id)} />
        ))}
      </div>
      
      {quickViewPrinter && (
        <QuickViewModal 
          printer={quickViewPrinter} 
          isLive={quickViewPrinter.id === activePrinter.id} 
          onClose={() => setQuickViewPrinter(null)} 
        />
      )}
    </div>
  );
}
