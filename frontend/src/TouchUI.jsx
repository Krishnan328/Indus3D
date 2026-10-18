import React, { useState } from "react";
import { Home, SlidersHorizontal, Settings, Database, Camera, Move, MoveUp, MoveDown, Droplet, Plus, Minus } from "lucide-react";
import { useStore, API } from "./store";

export function TouchUI() {
  const [activeTab, setActiveTab] = useState("home");
  
  const telemetry = useStore(s => s.telemetry);
  const isPrinting = telemetry.state === "printing";
  
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
              <TempCard label="Nozzle" temp={telemetry.extTemp} target={telemetry.extTarget} color="text-orange-400" />
              <TempCard label="Bed" temp={telemetry.bedTemp} target={telemetry.bedTarget} color="text-blue-400" />
              
              <div className="flex-1 bg-gradient-to-br from-[#112a20] to-[#1a1a1a] rounded-2xl p-4 border border-emerald-500/30 flex flex-col justify-between relative overflow-hidden">
                <div className="z-10">
                  <div className="text-emerald-400 font-bold uppercase tracking-widest text-sm flex items-center gap-2">
                    {isPrinting && <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>}
                    {telemetry.state}
                  </div>
                  <div className="text-white text-xl font-medium mt-1 truncate">{telemetry.filename || "Idle"}</div>
                </div>
                <div className="z-10 flex justify-between items-end">
                  <div className="text-6xl font-black text-white tracking-tighter">{(telemetry.progress * 100).toFixed(0)}<span className="text-3xl opacity-50">%</span></div>
                </div>
              </div>
            </div>

            {/* Bottom Row: Progress & Actions */}
            <div className="flex-1 flex gap-6">
              <div className="flex-1 bg-[#1a1a1a] rounded-2xl p-5 border border-[#333] flex flex-col justify-between">
                <div>
                  <div className="flex justify-between text-sm text-gray-400 mb-2 font-medium">
                    <span>Z: {telemetry.liveZ?.toFixed(2) || "0.00"} mm</span>
                  </div>
                  <div className="w-full bg-[#000] h-4 rounded-full overflow-hidden border border-[#333]">
                    <div className="h-full bg-emerald-500 rounded-full transition-all" style={{ width: `${telemetry.progress * 100}%` }}></div>
                  </div>
                </div>
                <div className="flex gap-4">
                  <QuickAction label="Z-Offset" icon={SlidersHorizontal} />
                  <QuickAction label="Flow/Speed" icon={Droplet} />
                </div>
              </div>

              <div className="w-40 flex flex-col gap-4">
                <button 
                  onClick={() => fetch(`${API}/api/v1/printer/restart`, { method: 'POST' })}
                  className="flex-1 bg-yellow-500/20 rounded-2xl flex flex-col items-center justify-center gap-2 text-yellow-500 hover:bg-yellow-500/30 active:scale-95 transition-all border border-yellow-500/30"
                >
                  <span className="font-bold text-lg">PAUSE</span>
                </button>
                <button 
                  onClick={() => fetch(`${API}/api/v1/printer/emergency_stop`, { method: 'POST' })}
                  className="flex-1 bg-red-500/20 rounded-2xl flex flex-col items-center justify-center gap-2 text-red-500 hover:bg-red-500/30 active:scale-95 transition-all border border-red-500/30"
                >
                  <span className="font-bold text-lg">STOP</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "controls" && (
          <ControlsTab />
        )}
      </div>
    </div>
  );
}

function ControlsTab() {
  const [xyStep, setXyStep] = useState(10);
  const zStep = 10;
  const [eStep, setEStep] = useState(10);

  const jog = (axis, dist) => fetch(`${API}/api/v1/control/jog`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [axis]: dist, speed: 3000 })
  });

  const home = () => fetch(`${API}/api/v1/control/home`, { method: "POST" });

  return (
    <div className="absolute inset-0 p-6 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-200 bg-[#0a0a0a]">
      <div className="flex justify-between items-center h-10">
        <h1 className="text-2xl font-bold text-white tracking-tight">Motion & Filament</h1>
        <div className="flex gap-2">
          <button onClick={home} className="px-6 py-2 bg-[#1a1a1a] border border-[#333] rounded-full text-white font-bold active:bg-[#333] flex items-center gap-2">Home All</button>
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
              <button onClick={home} className="z-10 bg-blue-500 text-white w-12 h-12 rounded-full font-bold shadow-lg flex items-center justify-center active:scale-90"><Home size={20}/></button>
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
          <h2 className="text-gray-400 font-bold tracking-widest uppercase text-sm mb-4">Filament</h2>
          
          <div className="flex-1 flex flex-col justify-center gap-4">
            <button onClick={()=>jog("e", eStep)} className="w-full py-5 bg-[#2a2a2a] active:scale-95 rounded-xl border border-[#444] text-emerald-400 font-bold text-xl">Extrude</button>
            <button onClick={()=>jog("e", -eStep)} className="w-full py-5 bg-[#2a2a2a] active:scale-95 rounded-xl border border-[#444] text-orange-400 font-bold text-xl">Retract</button>
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

function TempCard({ label, temp, target, color }) {
  return (
    <div className="w-48 bg-[#1a1a1a] rounded-2xl p-4 flex flex-col justify-between border border-[#333]">
      <div className="flex items-center gap-2 text-gray-400 font-medium">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className={`text-5xl font-bold ${color}`}>{temp?.toFixed(0) || "--"}</span>
        <span className="text-xl text-gray-500">/{target?.toFixed(0) || "0"}°C</span>
      </div>
    </div>
  );
}

function QuickAction({ label, icon }) {
  return (
    <button className="flex-1 py-4 bg-[#2a2a2a] rounded-xl flex items-center justify-center gap-2 text-white font-medium text-lg active:bg-[#333] border border-white/5">
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
