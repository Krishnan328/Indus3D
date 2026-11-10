import React, { useState } from "react";
import { Home, SlidersHorizontal, Settings, Database, Camera, Move, MoveUp, MoveDown, Droplet, Plus, Minus, X, Check, PowerOff } from "lucide-react";
import { useStore, API } from "./store";

export function TouchUI() {
  const [activeTab, setActiveTab] = useState("home");
  const [activeSheet, setActiveSheet] = useState(null); // 'zoffset' | 'flowspeed' | null
  
  const telemetry = useStore(s => s.telemetry);
  const pausePrint = useStore(s => s.pausePrint);
  const resumePrint = useStore(s => s.resumePrint);
  const cancelPrint = useStore(s => s.cancelPrint);
  const powerAction = useStore(s => s.powerAction);
  const setBabystep = useStore(s => s.setBabystep);
  const saveBabystep = useStore(s => s.saveBabystep);
  const setSpeedFactor = useStore(s => s.setSpeedFactor);
  const setFlowFactor = useStore(s => s.setFlowFactor);

  const isPrinting = telemetry.state === "printing";
  const isPaused = telemetry.state === "paused";
  const speedFactor = telemetry.speed_factor ?? 100;
  const flowFactor = telemetry.flow_factor ?? 100;

  return (
    <div className="flex h-screen w-screen bg-black text-white font-sans overflow-hidden">
      
      {/* Left Sidebar */}
      <div className="w-24 bg-[#111] border-r border-[#333] flex flex-col items-center py-6 gap-6 z-20 shrink-0">
        <NavButton icon={Home} active={activeTab === "home"} onClick={() => setActiveTab("home")} />
        <NavButton icon={Move} active={activeTab === "controls"} onClick={() => setActiveTab("controls")} />
        <NavButton icon={Database} active={activeTab === "spools"} onClick={() => setActiveTab("spools")} />
        <NavButton icon={Camera} active={activeTab === "cam"} onClick={() => setActiveTab("cam")} />
        <div className="flex-1" />
        <NavButton icon={Settings} active={activeTab === "settings"} onClick={() => setActiveTab("settings")} />
      </div>

      {/* Main Content Area */}
      <div className="flex-1 relative bg-[#0a0a0a]">
        
        {activeTab === "home" && (
          <div className="absolute inset-0 p-6 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-200">
            {/* Top Row: Temps & Active Print */}
            <div className="flex gap-6 h-40">
              <TempCard label="Nozzle" temp={telemetry.extTemp} target={telemetry.extTarget} color="text-orange-400" heaterKey="extruder" />
              <TempCard label="Bed" temp={telemetry.bedTemp} target={telemetry.bedTarget} color="text-blue-400" heaterKey="bed" />
              
              <div className="flex-1 bg-gradient-to-br from-[#112a20] to-[#1a1a1a] rounded-2xl p-4 border border-emerald-500/30 flex flex-col justify-between relative overflow-hidden">
                <div className="z-10">
                  <div className="text-emerald-400 font-bold uppercase tracking-widest text-sm flex items-center gap-2">
                    {isPrinting && <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>}
                    {telemetry.state || "Idle"}
                  </div>
                  <div className="text-white text-xl font-medium mt-1 truncate">{telemetry.filename || "No active job"}</div>
                </div>
                <div className="z-10 flex justify-between items-end">
                  <div className="text-6xl font-black text-white tracking-tighter">{((telemetry.progress || 0) * 100).toFixed(0)}<span className="text-3xl opacity-50">%</span></div>
                  <div className="text-right text-xs text-gray-400">
                    <div>Speed: <span className="text-white font-mono">{speedFactor}%</span></div>
                    <div>Flow: <span className="text-white font-mono">{flowFactor}%</span></div>
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom Row: Progress & Actions */}
            <div className="flex-1 flex gap-6">
              <div className="flex-1 bg-[#1a1a1a] rounded-2xl p-5 border border-[#333] flex flex-col justify-between">
                <div>
                  <div className="flex justify-between text-sm text-gray-400 mb-2 font-medium">
                    <span>Z: {telemetry.liveZ?.toFixed(2) || (telemetry.z !== undefined ? Number(telemetry.z).toFixed(2) : "0.00")} mm</span>
                    <span>Layers: {telemetry.current_layer || 0} / {telemetry.total_layers || 0}</span>
                  </div>
                  <div className="w-full bg-[#000] h-4 rounded-full overflow-hidden border border-[#333]">
                    <div className="h-full bg-emerald-500 rounded-full transition-all" style={{ width: `${(telemetry.progress || 0) * 100}%` }}></div>
                  </div>
                </div>
                <div className="flex gap-4">
                  <QuickAction label="Z-Offset" icon={SlidersHorizontal} onClick={() => setActiveSheet("zoffset")} />
                  <QuickAction label="Flow/Speed" icon={Droplet} onClick={() => setActiveSheet("flowspeed")} />
                </div>
              </div>

              <div className="w-40 flex flex-col gap-4">
                <button 
                  onClick={() => {
                    if (isPaused) {
                      resumePrint();
                    } else if (isPrinting) {
                      pausePrint();
                    }
                  }}
                  disabled={!isPrinting && !isPaused}
                  className={`flex-1 rounded-2xl flex flex-col items-center justify-center gap-2 active:scale-95 transition-all border ${
                    isPaused
                      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/30"
                      : "bg-yellow-500/20 text-yellow-500 border-yellow-500/30 hover:bg-yellow-500/30"
                  } ${(!isPrinting && !isPaused) ? "opacity-40 cursor-not-allowed" : ""}`}
                >
                  <span className="font-bold text-lg">{isPaused ? "RESUME" : "PAUSE"}</span>
                </button>
                <button 
                  onClick={() => {
                    if (isPrinting || isPaused) {
                      if (window.confirm?.("Cancel current print job?") !== false) {
                        cancelPrint();
                      }
                    } else {
                      powerAction("emergency_stop");
                    }
                  }}
                  className="flex-1 bg-red-500/20 rounded-2xl flex flex-col items-center justify-center gap-2 text-red-500 hover:bg-red-500/30 active:scale-95 transition-all border border-red-500/30"
                >
                  <span className="font-bold text-lg">{isPrinting || isPaused ? "CANCEL" : "STOP"}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "controls" && (
          <ControlsTab />
        )}

        {/* Modal / Sheet for Z-Offset */}
        {activeSheet === "zoffset" && (
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm z-30 flex items-center justify-center p-6 animate-in fade-in duration-150">
            <div className="bg-[#1a1a1a] border border-[#444] rounded-2xl p-6 w-full max-w-lg shadow-2xl flex flex-col gap-5">
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal size={22} className="text-emerald-400" />
                  <h2 className="text-xl font-bold text-white">Live Babystepping (Z-Offset)</h2>
                </div>
                <button onClick={() => setActiveSheet(null)} className="p-2 rounded-lg bg-[#2a2a2a] hover:bg-[#333] text-gray-400 hover:text-white">
                  <X size={20} />
                </button>
              </div>

              <p className="text-sm text-gray-400">Micro-adjust the nozzle clearance in real-time during first layers:</p>

              <div className="grid grid-cols-4 gap-3">
                {[-0.05, -0.01, 0.01, 0.05].map((offset) => (
                  <button
                    key={offset}
                    onClick={() => setBabystep(offset)}
                    className="py-4 bg-[#2a2a2a] hover:bg-[#333] active:scale-95 rounded-xl border border-white/10 text-white font-mono font-bold text-base flex flex-col items-center justify-center gap-1"
                  >
                    <span className={offset < 0 ? "text-cyan-400" : "text-amber-400"}>{offset > 0 ? `+${offset}` : offset}</span>
                    <span className="text-[10px] text-gray-400 font-sans">mm</span>
                  </button>
                ))}
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={async () => {
                    await saveBabystep();
                    alert("Z-offset applied to probe configuration.");
                  }}
                  className="flex-1 py-3 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-400 rounded-xl font-bold text-sm flex items-center justify-center gap-2 active:scale-95 transition-all"
                >
                  <Check size={18} />
                  Save to Probe Config
                </button>
                <button
                  onClick={() => setActiveSheet(null)}
                  className="px-6 py-3 bg-[#2a2a2a] hover:bg-[#333] border border-white/10 text-white rounded-xl font-bold text-sm"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Modal / Sheet for Flow & Speed */}
        {activeSheet === "flowspeed" && (
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm z-30 flex items-center justify-center p-6 animate-in fade-in duration-150">
            <div className="bg-[#1a1a1a] border border-[#444] rounded-2xl p-6 w-full max-w-lg shadow-2xl flex flex-col gap-6">
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <Droplet size={22} className="text-cyan-400" />
                  <h2 className="text-xl font-bold text-white">Speed & Flow Overrides</h2>
                </div>
                <button onClick={() => setActiveSheet(null)} className="p-2 rounded-lg bg-[#2a2a2a] hover:bg-[#333] text-gray-400 hover:text-white">
                  <X size={20} />
                </button>
              </div>

              {/* Speed Factor */}
              <div className="bg-[#111] p-4 rounded-xl border border-white/5 flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-semibold text-gray-300">Print Speed</span>
                  <span className="text-xl font-bold font-mono text-cyan-400">{speedFactor}%</span>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setSpeedFactor(speedFactor - 10)} className="flex-1 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg font-mono font-bold text-sm text-gray-200 active:scale-95">-10%</button>
                  <button onClick={() => setSpeedFactor(100)} className="px-4 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg text-xs font-semibold text-gray-400 hover:text-white">100%</button>
                  <button onClick={() => setSpeedFactor(speedFactor + 10)} className="flex-1 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg font-mono font-bold text-sm text-cyan-400 active:scale-95">+10%</button>
                </div>
              </div>

              {/* Flow Factor */}
              <div className="bg-[#111] p-4 rounded-xl border border-white/5 flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-semibold text-gray-300">Extrusion Flow</span>
                  <span className="text-xl font-bold font-mono text-emerald-400">{flowFactor}%</span>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setFlowFactor(flowFactor - 5)} className="flex-1 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg font-mono font-bold text-sm text-gray-200 active:scale-95">-5%</button>
                  <button onClick={() => setFlowFactor(100)} className="px-4 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg text-xs font-semibold text-gray-400 hover:text-white">100%</button>
                  <button onClick={() => setFlowFactor(flowFactor + 5)} className="flex-1 py-2.5 bg-[#2a2a2a] hover:bg-[#333] rounded-lg font-mono font-bold text-sm text-emerald-400 active:scale-95">+5%</button>
                </div>
              </div>

              <button
                onClick={() => setActiveSheet(null)}
                className="w-full py-3 bg-[#2a2a2a] hover:bg-[#333] border border-white/10 text-white rounded-xl font-bold text-sm"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ControlsTab() {
  const [xyStep, setXyStep] = useState(10);
  const zStep = 10;
  const [eStep, setEStep] = useState(10);

  const homeAxes = useStore(s => s.homeAxes);
  const homeAxis = useStore(s => s.homeAxis);
  const motorsOff = useStore(s => s.motorsOff);
  const extrudeFilament = useStore(s => s.extrudeFilament);
  const jogToolhead = useStore(s => s.jogToolhead);
  const extTemp = useStore(s => s.telemetry?.extTemp) || 0;
  const isCold = extTemp < 170;

  const jog = (axis, dist) => jogToolhead({ [axis]: dist }, 3000);

  return (
    <div className="absolute inset-0 p-6 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-200 bg-[#0a0a0a]">
      <div className="flex justify-between items-center h-10">
        <h1 className="text-2xl font-bold text-white tracking-tight">Motion & Filament</h1>
        <div className="flex gap-2">
          <button onClick={() => homeAxis?.("x")} className="px-3 py-1.5 bg-[#1a1a1a] border border-[#333] rounded-lg text-xs text-gray-300 font-mono font-bold hover:bg-[#333] active:scale-95">Home X</button>
          <button onClick={() => homeAxis?.("y")} className="px-3 py-1.5 bg-[#1a1a1a] border border-[#333] rounded-lg text-xs text-gray-300 font-mono font-bold hover:bg-[#333] active:scale-95">Home Y</button>
          <button onClick={() => homeAxis?.("z")} className="px-3 py-1.5 bg-[#1a1a1a] border border-[#333] rounded-lg text-xs text-gray-300 font-mono font-bold hover:bg-[#333] active:scale-95">Home Z</button>
          <button onClick={() => homeAxes?.()} className="px-4 py-1.5 bg-emerald-500/20 border border-emerald-500/40 rounded-lg text-xs text-emerald-400 font-bold active:bg-emerald-500/30 flex items-center gap-1.5">
            <Home size={14} /> Home All
          </button>
          <button onClick={() => motorsOff?.()} className="px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400 font-bold active:bg-red-500/20 flex items-center gap-1.5">
            <PowerOff size={14} /> Motors Off
          </button>
        </div>
      </div>

      <div className="flex-1 flex gap-6">
        {/* XY / Z Control */}
        <div className="flex-[1.5] bg-[#1a1a1a] rounded-2xl p-6 border border-[#333] flex flex-col">
          <h2 className="text-gray-400 font-bold tracking-widest uppercase text-sm mb-6">Axis Position</h2>
          
          <div className="flex flex-1 items-center justify-around">
            <div className="relative w-48 h-48 bg-[#111] rounded-full border-4 border-[#222] shadow-inner flex items-center justify-center">
              <button onClick={()=>jog("y", xyStep)} className="absolute top-2 bg-[#2a2a2a] p-3 rounded-full hover:bg-[#333] border border-[#444] text-white active:scale-90"><MoveUp size={24}/></button>
              <button onClick={()=>jog("y", -xyStep)} className="absolute bottom-2 bg-[#2a2a2a] p-3 rounded-full hover:bg-[#333] border border-[#444] text-white active:scale-90"><MoveDown size={24}/></button>
              <button onClick={()=>jog("x", -xyStep)} className="absolute left-2 bg-[#2a2a2a] p-3 rounded-full hover:bg-[#333] border border-[#444] text-white active:scale-90"><MoveUp size={24} className="-rotate-90"/></button>
              <button onClick={()=>jog("x", xyStep)} className="absolute right-2 bg-[#2a2a2a] p-3 rounded-full hover:bg-[#333] border border-[#444] text-white active:scale-90"><MoveUp size={24} className="rotate-90"/></button>
              <button onClick={() => homeAxes?.()} className="z-10 bg-blue-500 text-white w-12 h-12 rounded-full font-bold shadow-lg flex items-center justify-center active:scale-90"><Home size={20}/></button>
            </div>

            <div className="flex flex-col items-center gap-4">
              <button onClick={()=>jog("z", zStep)} className="w-16 h-16 bg-[#2a2a2a] rounded-2xl border border-[#444] text-white active:scale-90 flex flex-col justify-center items-center font-bold">+Z</button>
              <button onClick={()=>jog("z", -zStep)} className="w-16 h-16 bg-[#2a2a2a] rounded-2xl border border-[#444] text-white active:scale-90 flex flex-col justify-center items-center font-bold">-Z</button>
            </div>
          </div>

          <DistanceSelector value={xyStep} onChange={setXyStep} options={[0.1, 1, 10, 50]} />
        </div>

        {/* Filament */}
        <div className="flex-1 bg-[#1a1a1a] rounded-2xl p-6 border border-[#333] flex flex-col">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-gray-400 font-bold tracking-widest uppercase text-sm">Filament</h2>
            {isCold && (
              <span className="text-[11px] text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded border border-amber-400/20">
                Cold ({extTemp.toFixed(0)}°C &lt; 170°C)
              </span>
            )}
          </div>
          
          <div className="flex-1 flex flex-col justify-center gap-4">
            <button 
              onClick={() => {
                if (isCold) {
                  alert("Extruder temperature is below 170°C. Heat the nozzle before extruding.");
                  return;
                }
                extrudeFilament ? extrudeFilament(eStep) : jog("e", eStep);
              }} 
              className={`w-full py-5 rounded-xl border font-bold text-xl active:scale-95 transition-all ${
                isCold 
                  ? "bg-[#222] border-[#333] text-gray-500 cursor-not-allowed" 
                  : "bg-[#2a2a2a] border-[#444] text-emerald-400 hover:bg-[#333]"
              }`}
            >
              Extrude
            </button>
            <button 
              onClick={() => {
                if (isCold) {
                  alert("Extruder temperature is below 170°C. Heat the nozzle before retracting.");
                  return;
                }
                extrudeFilament ? extrudeFilament(-eStep) : jog("e", -eStep);
              }} 
              className={`w-full py-5 rounded-xl border font-bold text-xl active:scale-95 transition-all ${
                isCold 
                  ? "bg-[#222] border-[#333] text-gray-500 cursor-not-allowed" 
                  : "bg-[#2a2a2a] border-[#444] text-orange-400 hover:bg-[#333]"
              }`}
            >
              Retract
            </button>
          </div>
          
          <DistanceSelector value={eStep} onChange={setEStep} options={[1, 10, 50]} />
        </div>
      </div>
    </div>
  );
}

function NavButton({ icon, active, onClick }) {
  return (
    <button 
      onClick={onClick}
      className={`w-14 h-14 rounded-2xl flex flex-col items-center justify-center gap-1 active:scale-95 transition-all ${
        active ? "bg-emerald-500/20 text-emerald-400" : "text-gray-400 hover:text-white"
      }`}
    >
      {React.createElement(icon, { size: 24 })}
    </button>
  );
}

function TempCard({ label, temp, target, color, heaterKey }) {
  const setTemperature = useStore(s => s.setTemperature);

  const handleSet = (val) => {
    if (heaterKey) {
      setTemperature(heaterKey, val);
    }
  };

  const presets = heaterKey === "extruder" ? [200, 210, 240] : [50, 60, 80];

  return (
    <div className="w-52 bg-[#1a1a1a] rounded-2xl p-3 flex flex-col justify-between border border-[#333]">
      <div className="flex items-center justify-between text-gray-400 font-medium text-xs">
        <span>{label}</span>
        <button
          onClick={() => handleSet(0)}
          className="text-[10px] px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 active:bg-white/30 text-gray-300 font-mono"
        >
          Off
        </button>
      </div>
      <div className="flex items-baseline gap-1 my-1">
        <span className={`text-4xl font-bold ${color}`}>{temp?.toFixed(0) || "--"}</span>
        <span className="text-sm text-gray-500">/{target?.toFixed(0) || "0"}°C</span>
      </div>
      <div className="flex gap-1">
        {presets.map(p => (
          <button
            key={p}
            onClick={() => handleSet(p)}
            className="flex-1 py-1 rounded bg-[#2a2a2a] active:bg-[#333] text-[10px] font-mono font-bold text-gray-300 hover:text-white border border-white/5"
          >
            {p}°
          </button>
        ))}
      </div>
    </div>
  );
}

function QuickAction({ label, icon, onClick }) {
  return (
    <button 
      onClick={onClick}
      className="flex-1 py-4 bg-[#2a2a2a] rounded-xl flex items-center justify-center gap-2 text-white font-medium text-lg active:bg-[#333] border border-white/5 transition-all hover:bg-[#303030]"
    >
      {React.createElement(icon, { size: 24 })} {label}
    </button>
  );
}

function DistanceSelector({ value, onChange, options }) {
  return (
    <div className="flex justify-center mt-6 gap-2 bg-[#111] p-1.5 rounded-xl border border-[#333] w-max mx-auto">
      {options.map(opt => (
        <button 
          key={opt}
          onClick={() => onChange(opt)}
          className={`px-4 py-2 rounded-lg font-bold ${value === opt ? 'bg-emerald-500 text-black' : 'text-gray-400 active:bg-[#333]'}`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
