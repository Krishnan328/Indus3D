import React, { useState } from "react";
import { DatabaseBackup, RotateCcw, Trash2 } from "lucide-react";
import { useStore } from "../store";
import { useThemeTokens } from "../theme";
import { Btn, Card, ConfirmDialog, Resource } from "./shared";
import { printBusyState } from "./format";

const NAME_OK = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.db$/;

export function BackupsPanel() {
  const res = useStore((s) => s.systemData.backups);
  const createBackup = useStore((s) => s.createBackup);
  const restoreBackup = useStore((s) => s.restoreBackup);
  const deleteBackup = useStore((s) => s.deleteBackup);
  const busyPath = useStore((s) => s.systemBusy);
  const printState = useStore((s) => s.telemetry?.state);
  const printing = printBusyState(printState);
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const [pending, setPending] = useState(null);       // {kind: "restore"|"delete", file}
  const nameBad = name !== "" && !NAME_OK.test(name);

  const run = async () => {
    const p = pending;
    setPending(null);
    if (p.kind === "restore") await restoreBackup(p.file);
    else await deleteBackup(p.file);
  };

  return (
    <Resource res={res} what="Database backups">
      {(d) => (
        <Card title="Moonraker database backups">
          <p className="text-xs opacity-60 mb-3">Backs up Moonraker's database: job history, Mainsail/Fluidd settings, webcams, Spoolman links. Printer.cfg is not included.</p>
          {!d.supported ? (
            <div className={`p-3 text-xs ${t.cell}`}><b>Not available on this Moonraker.</b> {d.note || "Upgrade Moonraker to get database backups."}</div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <input aria-label="Backup file name (optional)" placeholder="name.db (optional)" value={name} onChange={(e) => setName(e.target.value)}
                  className={`px-2 py-1 text-xs border rounded bg-transparent w-48 ${nameBad ? "border-red-500" : t.border}`} />
                <Btn disabled={printing || !!busyPath || nameBad} title={printing ? "Refused during a print" : "Create a backup now"}
                  onClick={async () => { const r = await createBackup(name || undefined); if (r.ok) setName(""); }}><DatabaseBackup size={11} />Create backup</Btn>
                {nameBad && <span className="text-[11px] text-red-500">Letters, digits, _ - . and it must end in .db</span>}
              </div>
              {d.backups.length === 0 ? <p className="text-xs opacity-60">No backups yet.</p> : (
                <ul className="divide-y divide-gray-500/20">
                  {d.backups.map((b) => (
                    <li key={b.filename} className="py-2 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm break-all">{b.filename}</span>
                      <div className="ml-auto flex gap-1">
                        <Btn disabled={printing || !!busyPath} title={printing ? "Refused during a print" : "Restore this backup"} onClick={() => setPending({ kind: "restore", file: b.filename })}><RotateCcw size={11} />Restore</Btn>
                        <Btn danger disabled={!!busyPath} onClick={() => setPending({ kind: "delete", file: b.filename })}><Trash2 size={11} />Delete</Btn>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {pending && (
            <ConfirmDialog danger title={pending.kind === "restore" ? "Restore this backup?" : "Delete this backup?"}
              confirmLabel={pending.kind === "restore" ? "Restore" : "Delete"}
              body={pending.kind === "restore"
                ? <><p>The current Moonraker database is replaced by <b className="font-mono">{pending.file}</b>.</p><p>Moonraker restarts straight away; this page may show errors for a few seconds.</p></>
                : <p><b className="font-mono">{pending.file}</b> is deleted from the printer host for good.</p>}
              onConfirm={run} onCancel={() => setPending(null)} />
          )}
        </Card>
      )}
    </Resource>
  );
}
