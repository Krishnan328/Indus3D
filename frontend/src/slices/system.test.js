import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  createSystemSlice, dueKinds, reduceResource, actionMessage, INTERVALS, UPDATES_ACTIVE_MS, TAB_KINDS, TICK_MS,
} from "./systemSlice.js";

function makeStore() {
  let state = {};
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = createSystemSlice(set, get, () => "http://api");
  return { get, set };
}

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const flush = () => new Promise((r) => setImmediate(r));

let calls;
let responder;
let intervals;
let listeners;
beforeEach(() => {
  calls = [];
  intervals = [];
  listeners = {};
  globalThis.document = {
    hidden: false,
    addEventListener: (ev, fn) => { listeners[ev] = fn; },
    removeEventListener: (ev) => { delete listeners[ev]; },
  };
  globalThis.fetch = async (url, opts) => { calls.push({ url, opts }); return responder(url, opts); };
  globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
  globalThis.clearInterval = (id) => { if (intervals[id - 1]) intervals[id - 1].cleared = true; };
});

// ── pure logic ───────────────────────────────────────────────────────────────
test("dueKinds: alerts and the visible tab's data, each on its own interval", () => {
  assert.deepEqual(dueKinds({ now: 1000, last: {}, tab: "services", updatesActive: false }), ["alerts", "services"]);
  assert.deepEqual(dueKinds({ now: 1000, last: {}, tab: "host" }), ["alerts", "info"]);
  assert.deepEqual(dueKinds({ now: 1000, last: {}, tab: "mcus" }), ["alerts", "info"]);
  assert.deepEqual(dueKinds({ now: 1000, last: {}, tab: "devices" }), ["alerts", "peripherals"]);
  assert.deepEqual(dueKinds({ now: 1000, last: {}, tab: "nonsense" }), ["alerts"]);
});

test("dueKinds: nothing is refetched before its interval, then it is", () => {
  const last = { alerts: 0, info: 0 };
  assert.deepEqual(dueKinds({ now: INTERVALS.info - 1, last, tab: "host" }), []);
  assert.deepEqual(dueKinds({ now: INTERVALS.info, last, tab: "host" }), ["info"]);
  assert.deepEqual(dueKinds({ now: INTERVALS.alerts, last, tab: "host" }), ["alerts", "info"]);
});

test("dueKinds: update progress is followed closely only while an update is active", () => {
  const last = { alerts: 0, updates: 0 };
  assert.deepEqual(dueKinds({ now: UPDATES_ACTIVE_MS, last, tab: "updates", updatesActive: false }), []);
  assert.deepEqual(dueKinds({ now: UPDATES_ACTIVE_MS, last, tab: "updates", updatesActive: true }), ["updates"]);
});

test("polling budget stays well under the 120 requests/minute API limit", () => {
  // worst case: updates tab with an update running: 60/5 updates + 60/60 alerts per minute
  const perMinute = 60000 / UPDATES_ACTIVE_MS + 60000 / INTERVALS.alerts;
  assert.ok(perMinute <= 20, String(perMinute));
  for (const tab of Object.keys(TAB_KINDS)) {
    const rate = TAB_KINDS[tab].reduce((n, k) => n + 60000 / INTERVALS[k], 60000 / INTERVALS.alerts);
    assert.ok(rate < 30, `${tab}: ${rate}`);
  }
});

test("reduceResource: success, unsupported, and errors that keep the last good data", () => {
  const ok = reduceResource(undefined, 200, { ok: true, host: { os: "x" } });
  assert.equal(ok.ok, true); assert.equal(ok.data.host.os, "x"); assert.equal(ok.error, null);
  const bad = reduceResource(ok, 502, { ok: false, error: "Moonraker unreachable" });
  assert.equal(bad.ok, false); assert.equal(bad.error, "Moonraker unreachable"); assert.equal(bad.data.host.os, "x");
  const un = reduceResource(ok, 404, { ok: false, unsupported: true, error: "/x is not available on this Moonraker" });
  assert.equal(un.unsupported, true); assert.equal(un.data, null); assert.equal(un.ok, false);
  assert.equal(reduceResource(undefined, 500, null).error, "HTTP 500");
  assert.equal(reduceResource(undefined, 404, { error: "plain 404" }).unsupported, false);
});

test("actionMessage: rate limit and auth get plain wording", () => {
  assert.match(actionMessage(429, {}), /Too many requests/);
  assert.equal(actionMessage(409, { error: "A print is active" }), "A print is active");
  assert.equal(actionMessage(500, {}, "fallback"), "fallback");
  assert.equal(actionMessage(500, {}), "HTTP 500");
});

// ── fetching ─────────────────────────────────────────────────────────────────
test("fetchSystem stores the body and reports unsupported / error states", async () => {
  const s = makeStore();
  responder = () => json(200, { ok: true, host: { hostname: "voron" }, mcus: [] });
  await s.get().fetchSystem("info");
  assert.equal(calls[0].url, "http://api/api/v1/system/info");
  assert.equal(s.get().systemData.info.data.host.hostname, "voron");
  responder = () => json(404, { ok: false, unsupported: true, error: "gone" });
  await s.get().fetchSystem("updates");
  assert.equal(s.get().systemData.updates.unsupported, true);
  responder = () => { throw new Error("offline"); };
  await s.get().fetchSystem("info");
  assert.match(s.get().systemData.info.error, /offline/);
  assert.equal(s.get().systemData.info.data.host.hostname, "voron");
  await s.get().fetchSystem("bogus");
  assert.equal(calls.length, 3);
});

test("fetchSystem never overlaps itself and skips a hidden tab (unless forced)", async () => {
  let release;
  responder = () => new Promise((r) => { release = () => r(json(200, { ok: true })); });
  const s = makeStore();
  const first = s.get().fetchSystem("alerts");
  await s.get().fetchSystem("alerts");
  assert.equal(calls.length, 1);
  release(); await first;
  document.hidden = true;
  responder = () => json(200, { ok: true });
  await s.get().fetchSystem("alerts");
  assert.equal(calls.length, 1);
  await s.get().fetchSystem("alerts", { force: true });
  assert.equal(calls.length, 2);
});

// ── subscribe / polling ──────────────────────────────────────────────────────
test("nothing polls until subscribed; unsubscribing stops the timer and the visibility hook", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  assert.equal(calls.length, 0); assert.equal(intervals.length, 0);
  const off1 = s.get().subscribeSystem();
  const off2 = s.get().subscribeSystem();
  await flush();
  assert.equal(intervals.length, 1); assert.equal(intervals[0].ms, TICK_MS);
  assert.deepEqual(calls.map((c) => c.url).sort(), ["http://api/api/v1/system/alerts", "http://api/api/v1/system/info"]);
  assert.ok(listeners.visibilitychange);
  off1(); off1();
  assert.equal(s.get()._systemSubscribers(), 1); assert.ok(!intervals[0].cleared);
  off2();
  assert.equal(s.get()._systemSubscribers(), 0); assert.ok(intervals[0].cleared);
  assert.equal(listeners.visibilitychange, undefined);
});

test("a timer tick while the tab is hidden fetches nothing; becoming visible catches up", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  s.get().subscribeSystem();
  await flush();
  calls.length = 0;
  document.hidden = true;
  intervals[0].fn();
  await flush();
  assert.equal(calls.length, 0);
  document.hidden = false;
  listeners.visibilitychange();      // fresh data was fetched a moment ago: only what is due is requested
  await flush();
  assert.equal(calls.length, 0);
});

test("switching tab fetches that tab's data right away", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  s.get().subscribeSystem();
  await flush();
  calls.length = 0;
  s.get().setSystemTab("services");
  await flush();
  assert.deepEqual(calls.map((c) => c.url), ["http://api/api/v1/system/services"]);
  assert.equal(s.get().systemTab, "services");
});

test("a running update shortens the updates polling interval", async () => {
  const s = makeStore();
  responder = (url) => json(200, url.endsWith("/updates") ? { ok: true, components: [], job: { state: "running" } } : { ok: true });
  s.get().setSystemTab("updates");
  s.get().subscribeSystem();
  await flush();
  const realNow = Date.now;
  try {
    const t0 = realNow();
    Date.now = () => t0 + UPDATES_ACTIVE_MS + 10;
    calls.length = 0;
    intervals[0].fn();
    await flush();
    assert.deepEqual(calls.map((c) => c.url), ["http://api/api/v1/system/updates"]);
  } finally { Date.now = realNow; }
});

// ── actions ──────────────────────────────────────────────────────────────────
function lastPost() { return calls.filter((c) => c.opts && c.opts.method).slice(-1)[0]; }

test("serviceAction posts confirmed, adds confirm_self only on request, and refreshes services", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  const r = await s.get().serviceAction("crowsnest", "restart");
  assert.equal(r.ok, true);
  let p = lastPost();
  assert.equal(p.url, "http://api/api/v1/system/services/crowsnest/restart");
  assert.deepEqual(JSON.parse(p.opts.body), { confirmed: true });
  await s.get().serviceAction("indus3d", "stop", { confirmSelf: true });
  p = lastPost();
  assert.deepEqual(JSON.parse(p.opts.body), { confirmed: true, confirm_self: true });
  assert.ok(calls.some((c) => c.url === "http://api/api/v1/system/services" && !c.opts));
  assert.equal(s.get().systemNotice.tone, "ok");
  assert.equal(s.get().systemBusy, null);
});

test("service names are URL-encoded", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  await s.get().serviceAction("a b/c", "start");
  assert.equal(lastPost().url, "http://api/api/v1/system/services/a%20b%2Fc/start");
});

test("a refusal is returned and shown, not thrown", async () => {
  const s = makeStore();
  responder = (url, opts) => (opts ? json(409, { ok: false, busy: true, error: "A print is active" }) : json(200, { ok: true }));
  const r = await s.get().startUpdate("klipper");
  assert.equal(r.ok, false); assert.equal(r.status, 409); assert.equal(r.message, "A print is active");
  assert.equal(r.body.busy, true);
  assert.deepEqual(s.get().systemNotice && [s.get().systemNotice.tone, s.get().systemNotice.text], ["error", "A print is active"]);
  responder = () => json(429, {});
  assert.match((await s.get().startUpdate("klipper")).message, /Too many requests/);
  responder = () => { throw new Error("offline"); };
  const r3 = await s.get().startUpdate("klipper");
  assert.equal(r3.ok, false); assert.equal(r3.status, 0);
});

test("update, recover and backup actions hit the right routes with the right bodies", async () => {
  responder = () => json(200, { ok: true });
  const s = makeStore();
  await s.get().startUpdate("full");
  assert.equal(lastPost().url, "http://api/api/v1/system/updates/full");
  await s.get().recoverComponent("klipper", true);
  assert.equal(lastPost().url, "http://api/api/v1/system/updates/klipper/recover");
  assert.deepEqual(JSON.parse(lastPost().opts.body), { confirmed: true, hard: true });
  await s.get().createBackup("before.db");
  assert.deepEqual(JSON.parse(lastPost().opts.body), { confirmed: true, filename: "before.db" });
  await s.get().createBackup();
  assert.deepEqual(JSON.parse(lastPost().opts.body), { confirmed: true });
  await s.get().restoreBackup("old.db");
  assert.equal(lastPost().url, "http://api/api/v1/system/backups/old.db/restore");
  await s.get().deleteBackup("old.db");
  assert.equal(lastPost().opts.method, "DELETE");
  assert.equal(lastPost().url, "http://api/api/v1/system/backups/old.db");
});

test("dismissing an alert is remembered", () => {
  const s = makeStore();
  s.get().dismissSystemAlert("update:klipper:v1");
  assert.equal(s.get().systemDismissed["update:klipper:v1"], true);
});
