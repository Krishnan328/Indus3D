import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createFilesSlice, entriesFromListing, fileUrl } from "./filesSlice.js";

function makeStore() {
  let state = {};
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = { ...factoryState() };
  function factoryState() { return createFilesSlice(set, get, () => "http://api"); }
  return { get, set };
}

let calls;
let responder;
beforeEach(() => {
  calls = [];
  globalThis.document = { hidden: false };
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return responder(url, opts);
  };
});

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("listing entries and url helper", () => {
  const e = entriesFromListing({
    dirs: [{ name: "cal", path: "cal", modified: 1, permissions: "rw" }],
    files: [{ name: "a.gcode", path: "cal/a.gcode", size: 5, modified: 2, permissions: "rw", meta: { slicer: "Cura" }, has_meta: true }],
  });
  assert.deepEqual(e.map((x) => [x.type, x.path]), [["dir", "cal"], ["file", "cal/a.gcode"]]);
  assert.equal(e[1].meta.slicer, "Cura");
  assert.equal(fileUrl("http://api", "gcodes", "a b/c#.gcode", true),
    "http://api/api/v1/files/download?root=gcodes&path=a%20b%2Fc%23.gcode&inline=1");
});

test("fmOpen stores the listing; a stale response never overwrites a newer navigation", async () => {
  const s = makeStore();
  let release;
  responder = (url) => {
    if (url.includes("path=slow")) return new Promise((res) => { release = () => res(json(200, { root: "gcodes", path: "slow", dirs: [], files: [{ name: "old", path: "slow/old" }], writable: true })); });
    return json(200, { root: "gcodes", path: "fast", dirs: [], files: [{ name: "new", path: "fast/new" }], writable: true,
      disk_usage: { percent: 40 }, print: { busy: true, filename: "x.gcode" } });
  };
  const slow = s.get().fmOpen("gcodes", "slow");
  await s.get().fmOpen("gcodes", "fast");
  release();
  await slow;
  const fm = s.get().fm;
  assert.equal(fm.path, "fast");
  assert.deepEqual(fm.entries.map((e) => e.name), ["new"]);
  assert.equal(fm.diskUsage.percent, 40);
  assert.equal(fm.print.busy, true);
  assert.equal(fm.loading, false);
});

test("fmOpen reports unsupported and 502 distinctly", async () => {
  const s = makeStore();
  responder = () => json(501, { unsupported: true, error: "x" });
  await s.get().fmOpen("gcodes", "");
  assert.equal(s.get().fm.unsupported, true);
  assert.equal(s.get().fm.error, "Not available on this Moonraker");
  responder = () => json(502, { error: "down" });
  await s.get().fmOpen("gcodes", "");
  assert.equal(s.get().fm.unsupported, false);
  assert.equal(s.get().fm.error, "Moonraker is not reachable");
});

test("fmLoadRoots keeps the current root when it still exists, else falls back", async () => {
  const s = makeStore();
  responder = () => json(200, { roots: [{ name: "config" }, { name: "logs" }], simulator: true });
  await s.get().fmLoadRoots();
  assert.equal(s.get().fm.root, "config");
  assert.equal(s.get().fm.simulator, true);
});

test("thumbnails: one batched request, cached and de-duplicated", async () => {
  const s = makeStore();
  responder = () => json(200, { thumbs: { ".thumbs/a.png": "data:image/png;base64,AA" } });
  const items = [{ root: "gcodes", path: ".thumbs/a.png", v: 1 }, { root: "gcodes", path: ".thumbs/b.png", v: 1 }];
  await Promise.all([s.get().fmThumbsFor(items), s.get().fmThumbsFor(items)]);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].body.items, [{ path: ".thumbs/a.png", v: 1 }, { path: ".thumbs/b.png", v: 1 }]);
  assert.equal(s.get().fmThumbs["gcodes:.thumbs/a.png"], "data:image/png;base64,AA");
  assert.equal(s.get().fmThumbs["gcodes:.thumbs/b.png"], null);
  await s.get().fmThumbsFor(items);
  assert.equal(calls.length, 1);
});

test("thumbnail batches are capped and a 429 stops the rest", async () => {
  const s = makeStore();
  responder = () => json(429, {});
  const items = Array.from({ length: 70 }, (_, i) => ({ root: "gcodes", path: `.t/${i}.png` }));
  await s.get().fmThumbsFor(items);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.items.length, 30);
});

test("operations post typed bodies and refresh the listing on success", async () => {
  const s = makeStore();
  responder = (url) => (url.includes("/list") ? json(200, { root: "gcodes", path: "", dirs: [], files: [], writable: true }) : json(200, { ok: true }));
  await s.get().fmDelete("gcodes", ["a.gcode"], true);
  assert.deepEqual(calls[0].body, { root: "gcodes", items: ["a.gcode"], confirmed: true });
  await s.get().fmTransfer("move", "gcodes", ["a"], "sub", { overwrite: true });
  assert.deepEqual(calls[2].body, { root: "gcodes", items: ["a"], dest_dir: "sub", overwrite: true });
  await s.get().fmRename("gcodes", "a", "b");
  assert.equal(calls.at(-2).url, "http://api/api/v1/files/rename");
  assert.ok(calls.some((c) => c.url.includes("/list")));
  responder = () => json(409, { code: "confirmation_required", needs_confirmation: ["proj"], error: "needs" });
  const r = await s.get().fmDelete("gcodes", ["proj"]);
  assert.equal(r.ok, false);
  assert.deepEqual(r.body.needs_confirmation, ["proj"]);
});

// ── uploads with a fake XMLHttpRequest ─────────────────────────────────────────────────────────────────────
class FakeXhr {
  static all = [];
  constructor() { this.upload = {}; FakeXhr.all.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  send(form) { this.form = form; }
  abort() { this.onabort(); }
  reply(status, body) { this.status = status; this.responseText = JSON.stringify(body); this.onload(); }
}

test("uploads: progress, concurrency of two, conflict then overwrite", async () => {
  FakeXhr.all = [];
  globalThis.XMLHttpRequest = FakeXhr;
  globalThis.FormData = class { constructor() { this.f = []; } append(k, v) { this.f.push([k, v]); } };
  const s = makeStore();
  responder = () => json(200, { root: "gcodes", path: "", dirs: [], files: [], writable: true });
  const mk = (name, size) => ({ name, size });
  const ids = s.get().fmUpload("gcodes", "sub", [mk("a.gcode", 100), mk("b.gcode", 50), mk("c.gcode", 10)]);
  assert.equal(ids.length, 3);
  assert.equal(FakeXhr.all.length, 2);                                   // third waits
  assert.equal(s.get().fmUploads.filter((u) => u.status === "queued").length, 1);
  const x0 = FakeXhr.all[0];
  assert.ok(x0.url.endsWith("/api/v1/files/upload") && x0.withCredentials === true);
  assert.deepEqual(x0.form.f.slice(0, 2), [["root", "gcodes"], ["path", "sub"]]);
  x0.upload.onprogress({ lengthComputable: true, loaded: 40, total: 100 });
  assert.equal(s.get().fmUploads[0].loaded, 40);
  x0.reply(409, { code: "exists", error: "'a.gcode' already exists" });
  assert.equal(s.get().fmUploads[0].status, "exists");
  assert.equal(FakeXhr.all.length, 3);                                   // slot freed: c starts
  s.get().fmUploadResolve(ids[0], "overwrite");
  assert.equal(s.get().fmUploads[0].status, "queued");                   // both slots busy (b and c): waits its turn
  FakeXhr.all[1].reply(500, { error: "boom" });
  assert.equal(s.get().fmUploads[1].status, "error");
  assert.equal(s.get().fmUploads[1].error, "boom");
  assert.equal(s.get().fmUploads[0].status, "uploading");                // slot freed: the retry starts
  const retry = FakeXhr.all.at(-1);
  assert.ok(retry.form.f.some(([k, v]) => k === "overwrite" && v === "1"));
  retry.reply(200, { ok: true });
  assert.equal(s.get().fmUploads[0].status, "done");
  s.get().fmUploadCancel(ids[2]);
  assert.equal(s.get().fmUploads[2].status, "canceled");
  s.get().fmUploadsClear();
  assert.equal(s.get().fmUploads.length, 0);
});

// ── queue ──────────────────────────────────────────────────────────────────────────────────────────────────
const QSTATUS = { available: true, state: "paused", jobs: [{ id: "1", filename: "a" }, { id: "2", filename: "b" }, { id: "3", filename: "c" }],
  totals: { count: 3 }, note: "by hand", manual_start: true };

test("queue poll runs only while subscribed and is ref-counted", async () => {
  const s = makeStore();
  responder = () => json(200, QSTATUS);
  const intervals = [];
  const realSet = globalThis.setInterval;
  const realClear = globalThis.clearInterval;
  globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms, cleared: false }); return intervals.length - 1; };
  globalThis.clearInterval = (id) => { intervals[id].cleared = true; };
  try {
    const un1 = s.get().subscribeQueue(5000);
    const un2 = s.get().subscribeQueue(5000);
    assert.equal(intervals.length, 1);
    assert.equal(intervals[0].ms, 5000);
    await new Promise((r) => setImmediate(r));
    assert.equal(s.get().queue.state, "paused");
    assert.equal(s.get().queue.jobs.length, 3);
    un1();
    un1();                                                               // double unsubscribe is harmless
    assert.equal(intervals[0].cleared, false);
    un2();
    assert.equal(intervals[0].cleared, true);
  } finally {
    globalThis.setInterval = realSet;
    globalThis.clearInterval = realClear;
  }
});

test("queue is not fetched while the tab is hidden", async () => {
  const s = makeStore();
  responder = () => json(200, QSTATUS);
  globalThis.document = { hidden: true };
  await s.get().fetchQueue();
  assert.equal(calls.length, 0);
});

test("queue actions post typed bodies; reorder updates the list optimistically", async () => {
  const s = makeStore();
  responder = () => json(200, QSTATUS);
  await s.get().fetchQueue();
  calls.length = 0;
  await s.get().queueAdd(["a.gcode", "b.gcode"], { repeat: 3 });
  assert.deepEqual(calls[0].body, { filenames: ["a.gcode", "b.gcode"], repeat: 3 });
  assert.ok(calls[0].url.endsWith("/api/v1/queue/add"));
  await s.get().queueAdd(["x.gcode"], { position: "front" });
  assert.deepEqual(calls[2].body, { filenames: ["x.gcode"], position: "front" });
  await s.get().queueRemove(["1"]);
  assert.deepEqual(calls.at(-2).body, { ids: ["1"] });
  await s.get().queueClear();
  assert.deepEqual(calls.at(-2).body, { all: true });
  let seen;
  responder = (url) => { if (url.endsWith("/reorder")) seen = s.get().queue.jobs.map((j) => j.id); return json(200, QSTATUS); };
  await s.get().queueReorder(["3", "1", "2"]);
  assert.deepEqual(seen, ["3", "1", "2"]);                               // already reordered when the request went out
  const bad = await s.get().queueReorder(["1"]);
  assert.equal(bad.ok, false);
});

test("a missing [job_queue] marks the queue unavailable and keeps the snippet", async () => {
  const s = makeStore();
  responder = () => json(200, { available: false, setup: { snippet: "[job_queue]\n", file: "moonraker.conf" }, jobs: [] });
  await s.get().fetchQueue();
  assert.equal(s.get().queue.available, false);
  assert.match(s.get().queue.setup.snippet, /job_queue/);
  responder = () => json(501, { unsupported: true, code: "queue_unavailable", setup: { snippet: "[job_queue]\n" } });
  const r = await s.get().queueAdd(["a"]);
  assert.equal(r.ok, false);
  assert.equal(s.get().queue.available, false);
});
