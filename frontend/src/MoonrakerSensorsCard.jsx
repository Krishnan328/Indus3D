import React, { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Gauge } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens } from "./theme";
import { formatSensorValue, sensorParameters, sparklinePoints } from "./slices/thermalLogic";

// Moonraker [sensor ...] entries (MQTT sensors such as the ESP8266 bed hub's `bed_hub`, and anything else
// Moonraker's sensors component reports) with the latest values and a sparkline per value. When Moonraker
// has no bed_hub sensor, the esp_bed_hub plugin's own data is shown instead. Polled every 10 s while mounted
// (the API allows 120 requests a minute per client; the dashboard shares that).
const POLL_MS = 10000;

function Spark({ values }) {
  const points = sparklinePoints(values, 90, 22);
  if (!points) return <span className="text-[9px] opacity-40">no history</span>;
  return (
    <svg viewBox="0 0 90 22" className="w-[90px] h-[22px]" role="img" aria-label="history">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" opacity="0.8" />
    </svg>
  );
}

export function MoonrakerSensorsCard() {
  const t = useThemeTokens();
  const data = useStore((s) => s.thermalSensors);
  const fetchSensors = useStore((s) => s.fetchMoonrakerSensors);
  const [open, setOpen] = useState({});                       // id -> expanded (rows start collapsed)

  useEffect(() => {
    fetchSensors();
    const id = setInterval(fetchSensors, POLL_MS);
    return () => clearInterval(id);
  }, [fetchSensors]);

  return (
    <section className={`h-full min-h-[160px] p-4 flex flex-col ${t.panel}`} data-testid="sensors-card">
      <div className="flex items-center gap-2 mb-3 text-cyan-500"><Gauge size={16} /><h3 className={t.heading}>Sensors</h3>
        <span className="ml-auto text-[10px] opacity-50">{data.sensors.length ? `${data.sensors.length} sensor${data.sensors.length === 1 ? "" : "s"}` : ""}</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5">
        {data.sensors.map((sensor) => {
          const params = sensorParameters(sensor);
          const primary = params.find((p) => /^temp/i.test(p.key)) || params[0];
          const expanded = !!open[sensor.id];
          return (
            <div key={sensor.id} className={t.cell}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen({ ...open, [sensor.id]: !expanded })}
                className="w-full flex items-center gap-2 px-2 py-1.5 text-left">
                {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <span className="text-xs font-bold truncate">{sensor.friendly_name}</span>
                <span className="text-[9px] opacity-50">{sensor.source === "esp_bed_hub" ? "plugin" : sensor.type}</span>
                <span className="ml-auto font-mono text-xs">{primary ? formatSensorValue(primary.value, primary.unit) : "—"}</span>
              </button>
              {expanded && (
                <div className="px-2 pb-2 flex flex-col gap-1">
                  {params.map((p) => (
                    <div key={p.key} className="flex items-center gap-2 text-[11px]">
                      <span className="w-20 opacity-70 truncate">{p.label}</span>
                      <span className="font-mono w-20">{formatSensorValue(p.value, p.unit)}</span>
                      <span className="ml-auto"><Spark values={p.history} /></span>
                    </div>
                  ))}
                  {!params.length && <span className="text-[10px] opacity-50">No values reported.</span>}
                </div>
              )}
            </div>
          );
        })}
        {data.loaded && !data.sensors.length && (
          <div className="text-[11px] opacity-60 p-2">
            {data.ok ? "Moonraker reports no sensors. Add a [sensor ...] section (for example an MQTT sensor named bed_hub) to see it here."
              : `Sensors unavailable${data.error ? `: ${data.error}` : ""}.`}
          </div>
        )}
        {!data.loaded && <div className="text-xs italic opacity-45 p-2">Loading sensors…</div>}
        {data.loaded && !data.ok && data.sensors.length > 0 && <div className="text-[9px] opacity-50">Moonraker unreachable{data.error ? ` (${data.error})` : ""}: showing the last data.</div>}
      </div>
    </section>
  );
}
