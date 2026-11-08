import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createExcludeSlice, withExcluded, withoutExcluded, EXCLUDE_ERROR_MS } from "./excludeSlice.js";

function makeStore(initial = {}) {
  let state = {};
  const set = (patch) => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
  const get = () => state;
  state = { exclude_object: { objects: [{ name: "a" }, { name: "b" }], excluded_objects: [] }, ...initial, ...createExcludeSlice(set, get, () => "http://api") };
  return { get };
}

let responder;
let calls;
beforeEach(() => {
  calls = [];
  globalThis.fetch = async (url, opts) => { calls.push({ url, body: JSON.parse(opts.body) }); return responder(); };
});
afterEach(() => { delete globalThis.fetch; });

const res = (status, body) => ({ ok: status < 300, status, json: async () => body });

test("pure helpers add and remove a name without mutating", () => {
  const s = { exclude_object: { excluded_objects: ["x"] } };
  assert.deepEqual(withExcluded(s, "y").exclude_object.excluded_objects, ["x", "y"]);
  assert.equal(withExcluded(s, "x"), null);
  assert.deepEqual(withoutExcluded(s, "x").exclude_object.excluded_objects, []);
  assert.equal(withoutExcluded(s, "zz"), null);
  assert.deepEqual(s.exclude_object.excluded_objects, ["x"]);
});

test("success keeps the optimistic mark", async () => {
  responder = () => res(200, { success: true });
  const { get } = makeStore();
  assert.equal(await get().excludeObject("a"), true);
  assert.deepEqual(get().exclude_object.excluded_objects, ["a"]);
  assert.equal(get().excludeError, null);
  assert.deepEqual(calls[0].body, { name: "a" });
});

test("non-2xx rolls the mark back and surfaces the backend message", async () => {
  responder = () => res(422, { error: "Klipper refused the exclusion: nope" });
  const { get } = makeStore();
  assert.equal(await get().excludeObject("a"), false);
  assert.deepEqual(get().exclude_object.excluded_objects, []);
  assert.equal(get().excludeError.name, "a");
  assert.match(get().excludeError.message, /refused/);
  assert.equal(typeof get().excludeError.ts, "number");
  get().clearExcludeError();
  assert.equal(get().excludeError, null);
});

test("network failure rolls back; an already-excluded object is not un-excluded", async () => {
  responder = () => { throw new Error("offline"); };
  const { get } = makeStore({ exclude_object: { objects: [], excluded_objects: ["b"] } });
  await get().excludeObject("a");
  assert.deepEqual(get().exclude_object.excluded_objects, ["b"]);
  assert.match(get().excludeError.message, /offline/);
  await get().excludeObject("b");                      // was already excluded before the call
  assert.deepEqual(get().exclude_object.excluded_objects, ["b"]);
  get().clearExcludeError();
});

test("non-JSON error body falls back to a status message; error clears itself", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  responder = () => ({ ok: false, status: 502, json: async () => { throw new Error("html"); } });
  const { get } = makeStore();
  await get().excludeObject("a");
  assert.match(get().excludeError.message, /HTTP 502/);
  t.mock.timers.tick(EXCLUDE_ERROR_MS + 1);
  assert.equal(get().excludeError, null);
});
