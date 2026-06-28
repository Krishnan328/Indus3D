import time
from collections import deque
from config.loader import hotend, bed_heater, alerts_cfg

_HISTORY_LEN = 60

class ThermalModel:
    def __init__(self):
        self._ext_hist=deque(maxlen=_HISTORY_LEN); self._bed_hist=deque(maxlen=_HISTORY_LEN)
        self._ext_heat_cycles=0; self._bed_heat_cycles=0
        self._ext_was_hot=False; self._bed_was_hot=False
        self._ext_integral=0.; self._bed_integral=0.
        self._ext_prev_err=0.; self._bed_prev_err=0.
        self._last_ts=time.time()
        self._RUNAWAY_DELTA=alerts_cfg["thermal_runaway_delta_c"]
        self._RUNAWAY_WINDOW=alerts_cfg["thermal_runaway_window_s"]

    def update(self, snap):
        now=time.time(); dt=max(now-self._last_ts,1e-6); self._last_ts=now
        ext_t=snap["ext_temp"]; ext_tgt=snap["ext_target"]; ext_pwm=snap["ext_pwm"]
        bed_t=snap["bed_temp"]; bed_tgt=snap["bed_target"]
        self._ext_hist.append({"t":now,"temp":ext_t,"target":ext_tgt,"pwm":ext_pwm})
        self._bed_hist.append({"t":now,"temp":bed_t,"target":bed_tgt})
        if ext_tgt>40: self._ext_was_hot=True
        elif self._ext_was_hot and ext_t<40: self._ext_heat_cycles+=1; self._ext_was_hot=False
        if bed_tgt>40: self._bed_was_hot=True
        elif self._bed_was_hot and bed_t<40: self._bed_heat_cycles+=1; self._bed_was_hot=False
        ext_err=ext_tgt-ext_t; self._ext_integral+=ext_err*dt; ext_deriv=(ext_err-self._ext_prev_err)/dt; self._ext_prev_err=ext_err
        ext_pid=max(0.,min(1.,(hotend["pid_kp"]*ext_err+hotend["pid_ki"]*self._ext_integral+hotend["pid_kd"]*ext_deriv)/100.))
        bed_err=bed_tgt-bed_t; self._bed_integral+=bed_err*dt; bed_deriv=(bed_err-self._bed_prev_err)/dt; self._bed_prev_err=bed_err
        bed_pid=max(0.,min(1.,(bed_heater["pid_kp"]*bed_err+bed_heater["pid_ki"]*self._bed_integral+bed_heater["pid_kd"]*bed_deriv)/100.))
        return {
            "ext_error_c":round(ext_err,3),"ext_pid_shadow":round(ext_pid,4),
            "ext_pid_actual":round(ext_pwm,4),"ext_pid_delta":round(abs(ext_pid-ext_pwm),4),
            "ext_at_target":abs(ext_err)<2. and ext_tgt>0,"ext_runaway_flag":self._check_runaway(self._ext_hist),
            "ext_heat_cycles":self._ext_heat_cycles,"ext_max_temp":hotend["max_temp_c"],
            "bed_error_c":round(bed_err,3),"bed_pid_shadow":round(bed_pid,4),
            "bed_at_target":abs(bed_err)<2. and bed_tgt>0,"bed_runaway_flag":self._check_runaway(self._bed_hist),
            "bed_heat_cycles":self._bed_heat_cycles,"bed_max_temp":bed_heater["max_temp_c"],
        }

    def _check_runaway(self,hist):
        if len(hist)<10: return False
        window=[h for h in hist if time.time()-h["t"]<=self._RUNAWAY_WINDOW]
        if len(window)<5: return False
        avg_pwm=sum(w.get("pwm",0) for w in window)/len(window)
        if avg_pwm<0.8: return False
        return window[0]["temp"]-window[-1]["temp"]>self._RUNAWAY_DELTA

thermal_model = ThermalModel()
