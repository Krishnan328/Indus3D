import math, time
from collections import deque
from config.loader import hotend, print_cfg

_HISTORY_LEN = 30

class ExtrusionModel:
    def __init__(self):
        self._prev_e=0.; self._prev_ts=time.time(); self._filament_consumed_mm=0.
        self._flow_hist=deque(maxlen=_HISTORY_LEN)
        self._fil_dia=hotend["filament_diameter_mm"]; self._nozzle_dia=hotend["nozzle_diameter_mm"]
        self._layer_h=print_cfg["layer_height_mm"]; self._la_k=print_cfg["linear_advance_k"]
        self._max_flow=print_cfg["max_volumetric_flow_mm3_s"]
        self._fil_area=math.pi*(self._fil_dia/2)**2
        bw=self._nozzle_dia; bh=self._layer_h
        self._bead_area=(bw-bh)*bh+math.pi*(bh/2)**2

    def update(self, snap):
        now=time.time(); dt=max(now-self._prev_ts,1e-6); self._prev_ts=now
        cmd_e=snap["cmd_e"]; velocity=snap["velocity"]
        delta_e=cmd_e-self._prev_e; self._prev_e=cmd_e
        feed=max(0.,delta_e/dt) if delta_e>0 else 0.
        vol_flow=feed*self._fil_area; exp_flow=velocity*self._bead_area
        ratio=(vol_flow/exp_flow) if exp_flow>0.5 else 1.
        if delta_e>0: self._filament_consumed_mm+=delta_e
        self._flow_hist.append(vol_flow)
        avg_flow=sum(self._flow_hist)/max(len(self._flow_hist),1)
        return {
            "feed_rate_mm_s":round(feed,3),"volumetric_flow_mm3_s":round(vol_flow,4),
            "avg_flow_mm3_s":round(avg_flow,4),"expected_flow_mm3_s":round(exp_flow,4),
            "flow_ratio":round(ratio,3),
            "under_extrusion_flag":ratio<0.80 and velocity>10,
            "over_extrusion_flag":ratio>1.25 and velocity>10,
            "pressure_estimate_mm":round(self._la_k*velocity,4),
            "filament_consumed_m":round(self._filament_consumed_mm/1000.,4),
            "max_volumetric_flow":self._max_flow,
            "nozzle_dia_mm":self._nozzle_dia,"filament_dia_mm":self._fil_dia,"layer_height_mm":self._layer_h,
        }

extrusion_model = ExtrusionModel()
