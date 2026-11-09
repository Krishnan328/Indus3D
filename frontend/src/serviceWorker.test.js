import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const script = fs.readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const origin = "https://printer.invalid";
const response = (body) => ({ body, ok: true, type: "basic", clone() { return response(body); } });

function setup({ offline = false, storageDenied = false } = {}) {
  const handlers = {}, stored = new Map(), deleted = [];
  let calls = 0;
  const key = (request) => typeof request === "string" ? request : request.url;
  const context = {
    URL, Response: { error: () => ({ error: true }) },
    self: { location: { origin }, skipWaiting() {}, clients: { async claim() {} },
      addEventListener(name, fn) { handlers[name] = fn; } },
    caches: {
      async match(request) { return stored.get(key(request)); },
      async open() {
        if (storageDenied) throw new Error("quota denied");
        return { async put(request, value) { stored.set(key(request), value); } };
      },
      async keys() { return ["indus3d-cache-v1", "indus3d-cache-v2", "another-app"]; },
      async delete(name) { deleted.push(name); return true; },
    },
    async fetch() {
      calls++;
      if (offline) throw new Error("offline");
      return response("new deployment");
    },
  };
  vm.runInNewContext(script, context);
  return {
    stored, deleted, handlers, get calls() { return calls; },
    async request(path, overrides = {}) {
      let result;
      handlers.fetch({ request: { url: origin + path, method: "GET", mode: "cors", ...overrides },
        respondWith(value) { result = value; } });
      return result;
    },
  };
}

test("online navigation replaces a stale shell instead of pinning an old deployment", async () => {
  const worker = setup();
  worker.stored.set(origin + "/index.html", response("old UI"));
  assert.equal((await worker.request("/index.html")).body, "new deployment");
  assert.equal(worker.calls, 1);
  assert.equal(worker.stored.get(origin + "/index.html").body, "new deployment");
});

test("offline navigation can still show the cached shell", async () => {
  const worker = setup({ offline: true });
  worker.stored.set(origin + "/", response("offline shell"));
  assert.equal((await worker.request("/")).body, "offline shell");
});

test("APIs, websocket endpoints, external cameras and writes are never cached", async () => {
  const worker = setup();
  for (const [path, overrides] of [
    ["/api/v1/twin/state", {}], ["/server/info", {}], ["/ws", {}],
    ["/index.html", { method: "POST" }],
    ["/assets/camera.jpg", { url: "https://camera.invalid/assets/camera.jpg" }],
  ]) {
    assert.equal(await worker.request(path, overrides), undefined);
  }
  assert.equal(worker.calls, 0);
});

test("content-hashed assets use their cached version", async () => {
  const worker = setup();
  worker.stored.set(origin + "/assets/app-123.js", response("immutable"));
  assert.equal((await worker.request("/assets/app-123.js")).body, "immutable");
  assert.equal(worker.calls, 0);
});

test("quota denial cannot hide a good network response", async () => {
  const worker = setup({ storageDenied: true });
  assert.equal((await worker.request("/")).body, "new deployment");
});

test("activation clears only obsolete Indus3D caches", async () => {
  const worker = setup();
  let completed;
  worker.handlers.activate({ waitUntil(value) { completed = value; } });
  await completed;
  assert.deepEqual(worker.deleted, ["indus3d-cache-v1"]);
});
