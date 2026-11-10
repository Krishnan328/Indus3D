import React, { useEffect, useState } from "react";
import { X, Database, Plus, Trash2, CheckCircle2 } from "lucide-react";
import { API } from "./store";
import { useThemeTokens } from "./theme";

export function SpoolManager({ onClose }) {
  const t = useThemeTokens();
  const [spools, setSpools] = useState([]);
  const [loading, setLoading] = useState(true);
  
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMaterial, setNewMaterial] = useState("PLA");
  const [newColor, setNewColor] = useState("#ff0000");
  const [newWeight, setNewWeight] = useState(1000.0);

  const loadSpools = async () => {
    try {
      const res = await fetch(`${API}/api/v1/spools`);
      if (res.ok) setSpools(await res.json());
    } catch {
      // The empty state remains visible when the service is unreachable.
    }
    setLoading(false);
  };

  useEffect(() => {
    let active = true;
    fetch(`${API}/api/v1/spools`)
      .then((res) => res.ok ? res.json() : [])
      .then((data) => { if (active) setSpools(data); })
      .catch(() => { /* The empty state remains visible when unavailable. */ })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    try {
      await fetch(`${API}/api/v1/spools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newName,
          material: newMaterial,
          color_hex: newColor,
          starting_weight_g: newWeight
        })
      });
      setShowAdd(false);
      setNewName("");
      loadSpools();
    } catch {
      // Leave the dialog open so the user can retry.
    }
  };

  const handleSetActive = async (id) => {
    try {
      await fetch(`${API}/api/v1/spools/${id}/active`, { method: "POST" });
      loadSpools();
    } catch {
      // Retain the current local view if the request fails.
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this virtual spool?")) return;
    try {
      await fetch(`${API}/api/v1/spools/${id}`, { method: "DELETE" });
      loadSpools();
    } catch {
      // Retain the current local view if the request fails.
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-5 bg-black/60 backdrop-blur-sm">
      <div className={`w-full max-w-2xl max-h-[90vh] overflow-y-auto p-5 ${t.panel}`}>
        <header className="flex items-start justify-between gap-4 mb-5">
          <div>
            <div className="flex items-center gap-2 text-orange-400">
              <Database size={19} />
              <h2 className={t.heading}>Virtual Spool Manager</h2>
            </div>
            <p className="text-xs opacity-60 mt-1">Track material usage automatically from live extrusion telemetry.</p>
          </div>
          <button onClick={onClose} className="p-1 opacity-60 hover:opacity-100"><X size={20} /></button>
        </header>

        {!showAdd && (
          <button onClick={() => setShowAdd(true)} className={`mb-4 flex items-center gap-2 px-3 py-2 text-xs font-bold uppercase ${t.chip} bg-blue-600 text-white`}>
            <Plus size={14} /> Add New Spool
          </button>
        )}

        {showAdd && (
          <form onSubmit={handleAdd} className={`mb-6 p-4 border border-white/10 ${t.cell}`}>
            <h3 className="text-xs font-bold mb-3 uppercase tracking-wider opacity-70">New Virtual Spool</h3>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <label className="text-xs opacity-70">Name<input required value={newName} onChange={e=>setNewName(e.target.value)} className={`block w-full mt-1 p-2 ${t.cell}`} placeholder="e.g. PolyLite Black" /></label>
              <label className="text-xs opacity-70">Material<input required value={newMaterial} onChange={e=>setNewMaterial(e.target.value)} className={`block w-full mt-1 p-2 ${t.cell}`} /></label>
              <label className="text-xs opacity-70">Color<input type="color" value={newColor} onChange={e=>setNewColor(e.target.value)} className={`block w-full mt-1 h-8 p-0 cursor-pointer ${t.cell}`} /></label>
              <label className="text-xs opacity-70">Starting Weight (g)<input type="number" required value={newWeight} onChange={e=>setNewWeight(Number(e.target.value))} className={`block w-full mt-1 p-2 ${t.cell}`} /></label>
            </div>
            <div className="flex gap-2">
              <button type="submit" className={`px-3 py-1.5 text-xs font-bold uppercase bg-emerald-600 text-white ${t.chip}`}>Save Spool</button>
              <button type="button" onClick={() => setShowAdd(false)} className={`px-3 py-1.5 text-xs font-bold uppercase ${t.chip} ${t.cell}`}>Cancel</button>
            </div>
          </form>
        )}

        <div className="flex flex-col gap-3">
          {loading ? <div className="text-xs opacity-50 p-4">Loading spools...</div> : spools.length === 0 ? <div className="text-xs opacity-50 p-4 text-center">No spools configured.</div> : spools.map(s => {
            const remaining = Math.max(0, s.starting_weight_g - s.used_weight_g);
            const pct = Math.max(0, Math.min(100, (remaining / s.starting_weight_g) * 100));
            const isLow = pct < 15;
            
            return (
              <div key={s.id} className={`flex items-center gap-4 p-3 border ${s.is_active ? 'border-emerald-500 bg-emerald-500/5' : 'border-white/10'} ${t.cell}`}>
                <div className="w-8 h-8 rounded-full shrink-0 border-2 border-white/20" style={{ backgroundColor: s.color_hex }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm truncate">{s.name}</span>
                    <span className="text-[10px] font-mono opacity-60 px-1.5 py-0.5 bg-black/20 rounded">{s.material}</span>
                    {s.is_active ? <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-bold uppercase"><CheckCircle2 size={12}/> Active</span> : null}
                  </div>
                  <div className="flex items-center gap-3 mt-2">
                    <div className="flex-1 bg-black/40 h-2 rounded-full overflow-hidden">
                      <div className={`h-full transition-all ${isLow ? 'bg-red-500' : 'bg-blue-500'}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className={`text-[10px] font-mono shrink-0 ${isLow ? 'text-red-400 font-bold' : 'opacity-70'}`}>
                      {remaining.toFixed(1)}g / {s.starting_weight_g.toFixed(0)}g
                    </span>
                  </div>
                </div>
                
                <div className="flex flex-col gap-2 shrink-0">
                  {!s.is_active && (
                    <button onClick={() => handleSetActive(s.id)} className={`text-[10px] px-2 py-1 font-bold uppercase ${t.chip} border border-emerald-500 text-emerald-500 hover:bg-emerald-500 hover:text-white`}>
                      Set Active
                    </button>
                  )}
                  <button onClick={() => handleDelete(s.id)} className={`text-[10px] px-2 py-1 font-bold uppercase ${t.chip} opacity-50 hover:opacity-100 hover:bg-red-600 hover:text-white`}>
                    <Trash2 size={12} className="inline mr-1" /> Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
