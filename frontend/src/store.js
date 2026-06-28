import { create } from "zustand";

const HOST   = window.location.hostname;
const API    = `http://${HOST}:5001`;
const WS_URL = `ws://${HOST}:5001/ws/twin`;

let THRESHOLDS = {
  lag_magnitude_mm:  0.8,
  stress_score_axis: 0.5,
  ext_heat_cycles:   500,
  bed_heat_cycles:   500,
};

function deriveAlerts(data) {
  const alerts = [];
  const kin = data.kinematics || {};
  const thm = data.thermals   || {};
  const ext = data.extrusion  || {};

  if ((kin.lag_magnitude_mm ?? 0) > THRESHOLDS.lag_magnitude_mm)
    alerts.push({ id:"lag", level:"warn",
      msg:`Position lag ${kin.lag_magnitude_mm?.toFixed(2)} mm` });
  if (thm.ext_runaway_flag)
    alerts.push({ id:"ext_runaway", level:"critical", msg:"Extruder thermal runaway detected" });
  if (thm.bed_runaway_flag)
    alerts.push({ id:"bed_runaway", level:"critical", msg:"Bed thermal runaway detected" });
  if (ext.under_extrusion_flag)
    alerts.push({ id:"under_ext", level:"warn", msg:"Under-extrusion detected" });
  if (ext.over_extrusion_flag)
    alerts.push({ id:"over_ext",  level:"warn", msg:"Over-extrusion detected" });

  const stress = kin.stress_score || {};
  for (const axis of ["X","Y","Z"]) {
    if ((stress[axis] ?? 0) > THRESHOLDS.stress_score_axis)
      alerts.push({ id:`stress_${axis}`, level:"warn",
        msg:`${axis}-axis belt stress high (${stress[axis]?.toFixed(3)})` });
  }
  if ((thm.ext_heat_cycles ?? 0) > THRESHOLDS.ext_heat_cycles)
    alerts.push({ id:"ext_cycles", level:"info",
      msg:`Extruder heat cycles: ${thm.ext_heat_cycles}` });
  if ((thm.bed_heat_cycles ?? 0) > THRESHOLDS.bed_heat_cycles)
    alerts.push({ id:"bed_cycles", level:"info",
      msg:`Bed heat cycles: ${thm.bed_heat_cycles}` });
  return alerts;
}

export const useStore = create((set, get) => ({

  // ── Profile ───────────────────────────────────────────────────────────────
  profile:       null,
  profileSource: "",
  bed: { size_x_mm:300, size_y_mm:300, size_z_mm:400, origin_center:false },
  // simMode persists once set — never flips back to false mid-session
  simMode: false,

  fetchProfile: async () => {
    try {
      const res  = await fetch(`${API}/api/profile/`);
      const data = await res.json();
      const a = data.alerts ?? {};
      THRESHOLDS = {
        lag_magnitude_mm:  a.lag_magnitude_warn_mm  ?? 0.8,
        stress_score_axis: a.stress_score_warn       ?? 0.5,
        ext_heat_cycles:   a.ext_heat_cycles_warn    ?? 500,
        bed_heat_cycles:   a.bed_heat_cycles_warn    ?? 500,
      };
      set({ profile:data, profileSource:data._source ?? "unknown",
            bed: data.bed ?? get().bed });
    } catch {}
  },

  reloadProfile: async () => {
    try {
      const res  = await fetch(`${API}/api/profile/reload`,{method:"POST"});
      const data = await res.json();
      if (data.status==="ok"){ await get().fetchProfile(); return {ok:true}; }
      return {ok:false,message:data.message};
    } catch(e){ return {ok:false,message:e.toString()}; }
  },

  // ── Telemetry ─────────────────────────────────────────────────────────────
  telemetry: {
    x:0,y:0,z:0,extTemp:0,bedTemp:0,
    state:"standby",filename:"",file_position:0,fault:false,
    progress:0,print_duration:0,time_remaining:0,
    speed_factor:100,flow_factor:100,
  },

  kinematics: {
    odometry_m:{X:0,Y:0,Z:0,E:0},
    lag_x_mm:0,lag_y_mm:0,lag_z_mm:0,lag_magnitude_mm:0,
    derived_velocity_mm_s:0,accel_mm_s2:0,
    reversal_counts:{X:0,Y:0,Z:0},stress_score:{X:0,Y:0,Z:0},
  },
  thermals: {
    ext_error_c:0,ext_pid_shadow:0,ext_pid_actual:0,ext_pid_delta:0,
    ext_at_target:false,ext_runaway_flag:false,ext_heat_cycles:0,ext_max_temp:300,
    bed_error_c:0,bed_pid_shadow:0,bed_at_target:false,
    bed_runaway_flag:false,bed_heat_cycles:0,bed_max_temp:120,
  },
  extrusion: {
    feed_rate_mm_s:0,volumetric_flow_mm3_s:0,avg_flow_mm3_s:0,
    expected_flow_mm3_s:0,flow_ratio:1,under_extrusion_flag:false,
    over_extrusion_flag:false,pressure_estimate_mm:0,
    filament_consumed_m:0,max_volumetric_flow:12,
    nozzle_dia_mm:0.4,filament_dia_mm:1.75,layer_height_mm:0.2,
  },

  // ── Quality control ───────────────────────────────────────────────────────
  quality: {
    active:      { flow_pct:100, speed_pct:100, shaper_hz:0, enabled:false },
    corrections: [],
  },

  // ── Sensors ───────────────────────────────────────────────────────────────
  power:            {voltage:0,current:0,power:0},
  environment:      {temperature:0,humidity:0},
  printHistory:     [],
  maintenanceHints: [],

  fetchSensorData: async () => {
    try {
      const [pr,er,hr,mr] = await Promise.all([
        fetch(`${API}/api/power`),
        fetch(`${API}/api/environment`),
        fetch(`${API}/api/history`),
        fetch(`${API}/api/maintenance`),
      ]);
      if(pr.ok) set({power:      await pr.json()});
      if(er.ok) set({environment:await er.json()});
      if(hr.ok) set({printHistory:await hr.json()});
      if(mr.ok){const d=await mr.json();set({maintenanceHints:d.hints??[]});}
    } catch {}
  },

  // ── Alerts + action log ───────────────────────────────────────────────────
  alerts:       [],
  dismissedIds: new Set(),
  actionLog:    [],

  dismissAlert:   (id) => set((s) => ({dismissedIds:new Set([...s.dismissedIds,id])})),
  clearDismissed: ()   => set({dismissedIds:new Set()}),

  executeAlertAction: async (alertId) => {
    try {
      const res  = await fetch(`${API}/api/twin/action/execute`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({alert_id:alertId}),
      });
      const data = await res.json();
      if(data.status==="executed"){
        set((s)=>({actionLog:[{ts:Date.now(),...data},...s.actionLog].slice(0,100)}));
      }
      return data;
    } catch(e){ return {status:"error",message:e.toString()}; }
  },

  fetchActionLog: async () => {
    try {
      const res  = await fetch(`${API}/api/twin/action/log?limit=50`);
      set({actionLog:await res.json()});
    } catch {}
  },

  // ── Print controls ────────────────────────────────────────────────────────
  uploadAndPrint: async (file, startNow=false) => {
    const fd = new FormData();
    fd.append("file",file,file.name);
    const res = await fetch(`${API}/api/print/upload${startNow?"?start=1":""}`,
                            {method:"POST",body:fd});
    return res.json();
  },
  pausePrint:  async () => {await fetch(`${API}/api/print/pause`, {method:"POST"});},
  resumePrint: async () => {await fetch(`${API}/api/print/resume`,{method:"POST"});},
  cancelPrint: async () => {await fetch(`${API}/api/print/cancel`,{method:"POST"});},

  // ── Replay ────────────────────────────────────────────────────────────────
  replaySnapshots:[],replayCursor:0,replayPlaying:false,replayIntervalId:null,

  fetchReplaySnapshots: async(limit=500) => {
    try{
      const res=await fetch(`${API}/api/twin/snapshots?limit=${limit}`);
      set({replaySnapshots:await res.json(),replayCursor:0,replayPlaying:false});
    }catch{}
  },
  setReplayCursor:(idx)=>set({replayCursor:idx}),
  startReplay:()=>{
    const{replaySnapshots,replayCursor,replayIntervalId}=get();
    if(!replaySnapshots.length)return;
    if(replayIntervalId)clearInterval(replayIntervalId);
    let cursor=replayCursor;
    const id=setInterval(()=>{
      cursor++;
      if(cursor>=replaySnapshots.length){clearInterval(id);set({replayPlaying:false,replayIntervalId:null});return;}
      const snap=replaySnapshots[cursor];
      set({replayCursor:cursor,telemetry:{
        x:snap.cmd_x,y:snap.cmd_y,z:snap.cmd_z,
        extTemp:snap.ext_temp,bedTemp:snap.bed_temp,
        state:snap.print_state,filename:snap.filename,
        file_position:0,fault:false,
        progress:0,print_duration:0,time_remaining:0,speed_factor:100,flow_factor:100,
      }});
    },100);
    set({replayPlaying:true,replayIntervalId:id});
  },
  stopReplay:()=>{
    const{replayIntervalId}=get();
    if(replayIntervalId)clearInterval(replayIntervalId);
    set({replayPlaying:false,replayIntervalId:null});
  },

  gcodeLines:[],

  // ── WebSocket ─────────────────────────────────────────────────────────────
  wsRef:null,

  initWebSocket:()=>{
    let reconnectTimer=null;
    const connect=()=>{
      const ws=new WebSocket(WS_URL);

      ws.onopen=()=>{
        if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=null;}
      };

      ws.onmessage=(event)=>{
        try{
          const d=JSON.parse(event.data);
          const{dismissedIds}=get();
          const rawAlerts=deriveAlerts(d);
          const alerts=rawAlerts
            .filter(a=>!dismissedIds.has(a.id))
            .map(a=>({...a,ts:Date.now()}));

          // Auto-execute critical alerts only
          rawAlerts.filter(a=>a.level==="critical"&&!dismissedIds.has(a.id))
                   .forEach(a=>get().executeAlertAction(a.id));

          // simMode: once seen as true, stays true for the session
          const newSimMode = d.sim===true || get().simMode;

          let gcodeLines=get().gcodeLines;
          if(d.gcode_feed&&d.gcode_feed.length) gcodeLines=d.gcode_feed;

          set({
            telemetry:{
              x:          d.cmd_x        ??0,
              y:          d.cmd_y        ??0,
              z:          d.cmd_z        ??0,
              extTemp:    d.ext_temp     ??0,
              bedTemp:    d.bed_temp     ??0,
              state:      d.print_state  ??"unknown",
              filename:   d.filename     ??"",
              file_position:d.file_position??0,
              fault:      d.print_state  ==="error",
              progress:   d.progress     ??0,
              print_duration:d.print_duration??0,
              time_remaining:d.time_remaining??0,
              speed_factor:d.speed_factor??100,
              flow_factor:d.flow_factor  ??100,
            },
            kinematics: d.kinematics??{},
            thermals:   d.thermals  ??{},
            extrusion:  d.extrusion ??{},
            quality:    d.quality   ??get().quality,
            simMode:    newSimMode,
            alerts,
            gcodeLines,
            ...(d.power       ?{power:      d.power}      :{}),
            ...(d.environment ?{environment:d.environment}:{}),
          });
        }catch{}
      };

      ws.onerror=()=>ws.close();
      ws.onclose=()=>{
        set(s=>({telemetry:{...s.telemetry,fault:true}}));
        reconnectTimer=setTimeout(connect,2000);
      };
      set({wsRef:ws});
    };
    connect();
  },
}));

export { API };
