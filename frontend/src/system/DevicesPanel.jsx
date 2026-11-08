import React, { useState } from "react";
import { Cable, Usb } from "lucide-react";
import { API, useStore } from "../store";
import { useThemeTokens } from "../theme";
import { Btn, Card, ConfirmDialog, CopyButton, Resource } from "./shared";

function Unavailable({ part, what }) {
  const t = useThemeTokens();
  return <div className={`p-2 text-xs opacity-70 ${t.cell}`}>{part.unsupported ? `${what}: not available on this Moonraker` : `${what}: ${part.error || "unavailable"}`}</div>;
}

const KIND_HINT = {
  "by-id": "Recommended: stays the same when you replug or reboot",
  "by-path": "Depends on the USB port. This board has no unique ID; do not move it to another port",
  device: "Not a stable name: it can change between boots",
};

function SerialList({ part }) {
  const t = useThemeTokens();
  if (!part.available) return <Unavailable part={part} what="Serial devices" />;
  if (!part.items.length) return <p className="text-xs opacity-60">No serial devices found.</p>;
  return (
    <ul className="divide-y divide-gray-500/20">
      {part.items.map((d) => (
        <li key={d.device_path} className="py-2">
          <div className="flex flex-wrap items-center gap-2">
            <Cable size={13} className="opacity-60" />
            <span className="font-mono text-sm">{d.device_path}</span>
            <span className="text-[10px] opacity-50">{d.device_type}{d.driver_name ? `, ${d.driver_name}` : ""}</span>
          </div>
          {d.device_type === "usb" ? (
            <div className="mt-1 ml-5 flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs break-all select-all">serial: {d.recommended_path}</span>
              <CopyButton text={d.recommended_path} />
              <span className={`text-[10px] px-2 py-0.5 ${t.chip} ${d.recommended_kind === "by-id" ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>{d.recommended_kind}</span>
              <span className="text-[10px] opacity-60 basis-full">{KIND_HINT[d.recommended_kind]}</span>
              {d.recommended_kind === "by-id" && d.path_by_hardware && <span className="text-[10px] font-mono opacity-50 basis-full break-all">by-path: {d.path_by_hardware}</span>}
            </div>
          ) : <span className="ml-5 text-[11px] opacity-50">Hardware UART: use the device path above in the printer config.</span>}
        </li>
      ))}
    </ul>
  );
}

function SuspectTable({ health }) {
  const t = useThemeTokens();
  if (!health) return <p className="text-xs opacity-60">The USB link health plugin is not running on this Indus3D install.</p>;
  if (!health.suspects?.length) {
    return <p className="text-xs text-emerald-500">No unstable USB port or cable has been seen{health.kernel_log === "unreadable (sysfs-only)" ? " (kernel log unreadable: sysfs only)" : ""}.</p>;
  }
  return (
    <ul className="space-y-2">
      {health.suspects.map((s, i) => (
        <li key={s.path || i} className={`p-2 text-xs ${t.cell}`}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-bold">{s.path}</span>
            {s.device && <span>{s.device}{s.is_hub ? " (hub)" : ""}</span>}
            <span className="text-[10px] opacity-60">score {s.score}</span>
          </div>
          <p className="opacity-70">
            {s.drops} drop(s), {s.protocol_errors} protocol error(s){s.cable_errors ? `, ${s.cable_errors} cable error(s)` : ""}
            {s.hub_tiers_deep != null ? `, ${s.hub_tiers_deep} hub tier(s) deep` : ""}
            {s.carries?.length ? `; carries ${s.carries.join(", ")}` : ""}
          </p>
          {(s.likely || []).map((r, k) => <p key={k} className="opacity-90">{r}</p>)}
        </li>
      ))}
    </ul>
  );
}

export function DevicesPanel() {
  const res = useStore((s) => s.systemData.peripherals);
  const [canAsk, setCanAsk] = useState(false);
  const [can, setCan] = useState(null);
  const [canBusy, setCanBusy] = useState(false);

  const scanCan = async () => {
    setCanAsk(false);
    setCanBusy(true);
    try {
      const r = await fetch(`${API}/api/v1/system/peripherals?canbus=can0`);
      const body = await r.json().catch(() => ({}));
      setCan(r.ok ? body.canbus : { available: false, items: [], error: body.error || `HTTP ${r.status}` });
    } catch (e) {
      setCan({ available: false, items: [], error: String(e) });
    } finally {
      setCanBusy(false);
    }
  };

  return (
    <Resource res={res} what="Device listing">
      {(d) => (
        <div className="flex flex-col gap-4">
          <Card title="Serial devices (for Klipper's serial: option)"><SerialList part={d.serial} /></Card>

          <Card title="USB link health" right={<Usb size={14} className="opacity-50" />}>
            <p className="text-[11px] opacity-60 mb-2">Ranks the ports, hubs and cables behind USB disconnects ("Lost communication with MCU"). Measured on the machine running Indus3D.</p>
            <SuspectTable health={d.link_health} />
          </Card>

          <Card title="USB devices">
            {!d.usb.available ? <Unavailable part={d.usb} what="USB devices" /> : (
              <ul className="divide-y divide-gray-500/20 text-xs">
                {d.usb.items.map((u, i) => (
                  <li key={`${u.usb_location}-${i}`} className="py-1.5 flex flex-wrap gap-x-3">
                    <span className="font-mono opacity-60">{u.usb_location}</span>
                    <span>{u.description || u.product}</span>
                    <span className="font-mono opacity-50">{u.vendor_id}:{u.product_id}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="CAN bus">
            <p className="text-[11px] opacity-60 mb-2">Finding unassigned CAN nodes sends a query on the bus. With several unassigned nodes this can put them in "bus off" until they are reset, so it only runs when you ask.</p>
            <Btn disabled={canBusy} onClick={() => setCanAsk(true)}>Scan can0 for unassigned nodes</Btn>
            {can && (can.available ? (
              can.items.length === 0 ? <p className="mt-2 text-xs opacity-70">No unassigned CAN nodes answered.</p> : (
                <ul className="mt-2 text-xs font-mono">{can.items.map((c) => <li key={c.uuid} className="flex items-center gap-2">{c.uuid} <span className="opacity-60">{c.application}</span><CopyButton text={c.uuid} /></li>)}</ul>
              )
            ) : <div className="mt-2"><Unavailable part={can} what="CAN bus" /></div>)}
          </Card>

          <Card title="Video devices">
            {!d.video.available ? <Unavailable part={d.video} what="Video devices" /> : d.video.items.length === 0 ? <p className="text-xs opacity-60">No video devices found.</p> : (
              <ul className="divide-y divide-gray-500/20 text-xs">
                {d.video.items.map((v) => (
                  <li key={v.device_path} className="py-1.5 flex flex-wrap items-center gap-2">
                    <span className="font-mono">{v.device_path}</span>
                    <span className="opacity-70">{v.camera_name || v.driver_name}</span>
                    {v.recommended_path && v.recommended_path !== v.device_path && <><span className="font-mono opacity-50 break-all">{v.recommended_path}</span><CopyButton text={v.recommended_path} /></>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {canAsk && (
            <ConfirmDialog title="Scan the CAN bus?" confirmLabel="Scan" onConfirm={scanCan} onCancel={() => setCanAsk(false)}
              body={<p>Only do this when a single unassigned node is connected. Nodes that Klipper or Katapult already activated do not answer.</p>} />
          )}
        </div>
      )}
    </Resource>
  );
}
