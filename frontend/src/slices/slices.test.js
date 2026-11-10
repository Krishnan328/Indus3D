import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createPrinterStatusSlice } from "./printerStatusSlice.js";
import { createMacroSlice } from "./macroSlice.js";

// A minimal zustand-like store for the slice factories.
function makeStore(factory, initial = {}) {
  let state = { ...initial };
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = { ...state, ...factory(set, get, () => "http://api") };
  return { get, set };
}

let calls;
let responder;
beforeEach(() => {
  calls = [];
  globalThis.document = { hidden: false };
  globalThis.window = { confirm: () => true };
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts });
    return responder(url, opts);
  };
});

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

// ── printer status ───────────────────────────────────────────────────────────
test("status: stores status, capabilities and limits", async () => {
  responder = () => json(200, { ok: true, ts: 5, status: { fan: { speed: 1 } }, capabilities: { probe: true }, limits: { extruder: { max_temp: 285 } } });
  const s = makeStore((set, get, api) => createPrinterStatusSlice(set, get, api));
  await s.get().fetchPrinterStatus();
  const ps = s.get().printerStatus;
  assert.equal(ps.ok, true);
  assert.equal(ps.status.fan.speed, 1);
  assert.equal(ps.capabilities.probe, true);
  assert.equal(ps.limits.extruder.max_temp, 285);
  assert.equal(calls[0].url, "http://api/api/v1/printer/status");
});

test("status: an error keeps the last good data and reports the problem", async () => {
  const s = makeStore((set, get, api) => createPrinterStatusSlice(set, get, api));
  responder = () => json(200, { ok: true, ts: 1, status: { fan: { speed: 0.4 } }, capabilities: {}, limits: {} });
  await s.get().fetchPrinterStatus();
  responder = () => json(502, { ok: false, error: "Moonraker unreachable" });
  await s.get().fetchPrinterStatus();
  assert.equal(s.get().printerStatus.ok, false);
  assert.equal(s.get().printerStatus.error, "Moonraker unreachable");
  assert.equal(s.get().printerStatus.status.fan.speed, 0.4);
  responder = () => { throw new Error("offline"); };
  await s.get().fetchPrinterStatus();
  assert.match(s.get().printerStatus.error, /offline/);
});

test("status: does not poll while the tab is hidden and never overlaps itself", async () => {
  let release;
  responder = () => new Promise((r) => { release = () => r(json(200, { ok: true, ts: 1, status: {}, capabilities: {}, limits: {} })); });
  const s = makeStore((set, get, api) => createPrinterStatusSlice(set, get, api));
  const first = s.get().fetchPrinterStatus();
  await s.get().fetchPrinterStatus();                     // second call while the first is in flight
  assert.equal(calls.length, 1);
  release(); await first;
  globalThis.document.hidden = true;
  await s.get().fetchPrinterStatus();
  assert.equal(calls.length, 1);
});

test("status: polling starts with the first subscriber and stops with the last", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  responder = () => json(200, { ok: true, ts: 1, status: {}, capabilities: {}, limits: {} });
  const s = makeStore((set, get, api) => createPrinterStatusSlice(set, get, api));
  assert.equal(calls.length, 0);                          // nothing polls until someone subscribes
  const off1 = s.get().subscribePrinterStatus(1000);
  const off2 = s.get().subscribePrinterStatus(1000);
  assert.equal(s.get()._printerStatusSubscribers(), 2);
  assert.equal(calls.length, 1);                          // immediate fetch, once
  const settle = () => new Promise((r) => setImmediate(r));
  await settle();                                         // let the first request finish (no overlap allowed)
  t.mock.timers.tick(1000);
  await settle();
  assert.equal(calls.length, 2);                          // one more per interval, not one per subscriber
  t.mock.timers.tick(1000);
  await settle();
  assert.equal(calls.length, 3);
  off1(); off1();                                         // unsubscribing twice must not underflow
  assert.equal(s.get()._printerStatusSubscribers(), 1);
  off2();
  const n = calls.length;
  t.mock.timers.tick(5000);
  await new Promise((r) => setImmediate(r));
  assert.equal(calls.length, n);
});

// ── macros ───────────────────────────────────────────────────────────────────────
test("macro: posts to the typed endpoint with params, name URL-encoded", async () => {
  responder = () => json(200, { status: "ok" });
  const s = makeStore((set, get, api) => createMacroSlice(set, get, api), { telemetry: { state: "standby" } });
  const r = await s.get().runMacro("BED_CRASH_RESUME", { value: 2500 });
  assert.equal(r.ok, true);
  assert.equal(calls[0].url, "http://api/api/v1/printer/macro/BED_CRASH_RESUME");
  assert.deepEqual(JSON.parse(calls[0].opts.body), { params: { value: 2500 } });
  assert.equal(s.get().macroStatus.ok, true);
});

test("macro: during a print asks first and sends confirmed=true; declining sends nothing", async () => {
  responder = () => json(200, { status: "ok" });
  const s = makeStore((set, get, api) => createMacroSlice(set, get, api), { telemetry: { state: "printing" } });
  let asked = 0;
  globalThis.window.confirm = () => { asked += 1; return false; };
  const r = await s.get().runMacro("CLEAN_NOZZLE");
  assert.equal(r.ok, false);
  assert.equal(r.message, "cancelled");
  assert.equal(calls.length, 0);
  globalThis.window.confirm = () => { asked += 1; return true; };
  await s.get().runMacro("CLEAN_NOZZLE");
  assert.equal(JSON.parse(calls[0].opts.body).confirmed, true);
  assert.equal(asked, 2);
});

test("macro: PAUSE and RESUME never ask", async () => {
  responder = () => json(200, { status: "ok" });
  const s = makeStore((set, get, api) => createMacroSlice(set, get, api), { telemetry: { state: "printing" } });
  globalThis.window.confirm = () => { throw new Error("must not ask"); };
  assert.equal((await s.get().runMacro("pause")).ok, true);
  assert.equal((await s.get().runMacro("RESUME")).ok, true);
});

test("macro: a 409 from a print that started meanwhile is confirmed and retried once", async () => {
  let n = 0;
  responder = () => (++n === 1 ? json(409, { error: "A print is active", needs_confirmation: true }) : json(200, { status: "ok" }));
  const s = makeStore((set, get, api) => createMacroSlice(set, get, api), { telemetry: { state: "standby" } });
  const r = await s.get().runMacro("X");
  assert.equal(r.ok, true);
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(calls[1].opts.body).confirmed, true);
});

test("macro: server errors and network failures are reported, not thrown", async () => {
  const s = makeStore((set, get, api) => createMacroSlice(set, get, api), { telemetry: { state: "standby" } });
  responder = () => json(404, { error: "Klipper has no macro named 'X'" });
  assert.deepEqual(await s.get().runMacro("X"), { ok: false, message: "Klipper has no macro named 'X'" });
  responder = () => json(422, { detail: "Unknown command" });
  assert.equal((await s.get().runMacro("X")).message, "Unknown command");
  responder = () => { throw new Error("offline"); };
  assert.match((await s.get().runMacro("X")).message, /offline/);
});
