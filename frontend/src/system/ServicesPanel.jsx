import React, { useState } from "react";
import { RotateCw, Play, Square } from "lucide-react";
import { useStore } from "../store";
import { useThemeTokens } from "../theme";
import { Btn, Card, ConfirmDialog, Resource } from "./shared";
import { STATE_TONE, printBusyState } from "./format";

const VERBS = { restart: "Restart", start: "Start", stop: "Stop" };

export function ServicesPanel() {
  const res = useStore((s) => s.systemData.services);
  const serviceAction = useStore((s) => s.serviceAction);
  const busyPath = useStore((s) => s.systemBusy);
  const printState = useStore((s) => s.telemetry?.state);
  const printing = printBusyState(printState);
  const t = useThemeTokens();
  const [pending, setPending] = useState(null);       // {svc, action}

  const run = async ({ extra }) => {
    const { svc, action } = pending;
    setPending(null);
    await serviceAction(svc.name, action, { confirmSelf: svc.is_self && action === "stop" && extra });
  };

  return (
    <Resource res={res} what="Service control">
      {(d) => (
        <Card title="System services" right={<span className="text-[10px] opacity-60">via Moonraker ({d.provider || "no provider"})</span>}>
          {!d.manageable && <p className={`p-2 mb-3 text-xs ${t.cell}`}>Moonraker has no service provider, so services can be listed but not controlled.</p>}
          {printing && <p className="p-2 mb-3 text-xs text-amber-500 border border-amber-500/40 rounded">A print is active: Klipper and Moonraker cannot be restarted or stopped until it ends.</p>}
          <ul className="divide-y divide-gray-500/20">
            {d.services.map((svc) => {
              const locked = printing && svc.print_critical;
              return (
                <li key={svc.name} className="py-2 flex flex-wrap items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${STATE_TONE[svc.active_state] || "bg-gray-400"}`} />
                  <span className="font-mono text-sm">{svc.name}</span>
                  <span className="text-[11px] opacity-60">{svc.active_state}{svc.sub_state ? ` (${svc.sub_state})` : ""}</span>
                  {svc.is_self && <span className={`text-[10px] px-2 py-0.5 ${t.chip} bg-blue-500/20 text-blue-400`}>serves Indus3D</span>}
                  <div className="ml-auto flex gap-1">
                    {Object.keys(VERBS).map((action) => (
                      <Btn key={action} danger={action === "stop"} disabled={!d.manageable || !!busyPath || (locked && action !== "start")}
                        title={locked && action !== "start" ? "Refused during a print" : `${VERBS[action]} ${svc.name}`}
                        onClick={() => setPending({ svc, action })}>
                        {action === "restart" ? <RotateCw size={11} /> : action === "start" ? <Play size={11} /> : <Square size={11} />}{VERBS[action]}
                      </Btn>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
          {pending && (
            <ConfirmDialog
              danger={pending.action === "stop" || pending.svc.print_critical}
              title={`${VERBS[pending.action]} ${pending.svc.name}?`}
              confirmLabel={VERBS[pending.action]}
              body={<>
                <p>Moonraker will {pending.action} the <b>{pending.svc.name}</b> service.</p>
                {pending.svc.print_critical && pending.action !== "start" && <p>Klipper/Moonraker go offline for a moment; the printer must be idle.</p>}
                {pending.svc.is_self && <p>This is the service that serves Indus3D. {pending.action === "restart" ? "The page reconnects when it is back." : "Stopping it takes this page offline and it cannot be started again from here."}</p>}
              </>}
              extra={pending.svc.is_self && pending.action === "stop" ? { label: "I understand this page will go offline and I must start the service by hand." } : null}
              onConfirm={run} onCancel={() => setPending(null)} />
          )}
        </Card>
      )}
    </Resource>
  );
}
