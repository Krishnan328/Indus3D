import { test } from "node:test";
import assert from "node:assert/strict";
import { debounce } from "./debounce.js";

test("sends only the last value once it settles", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const sent = [];
  const send = debounce((v) => sent.push(v), 200);
  send(1); send(2); send(3);
  t.mock.timers.tick(199);
  assert.deepEqual(sent, []);
  t.mock.timers.tick(1);
  assert.deepEqual(sent, [3]);
});

test("each burst is separate", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const sent = [];
  const send = debounce((v) => sent.push(v), 100);
  send("a"); t.mock.timers.tick(100);
  send("b"); t.mock.timers.tick(100);
  assert.deepEqual(sent, ["a", "b"]);
});

test("flush sends immediately, once; cancel drops", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const sent = [];
  const send = debounce((v) => sent.push(v), 500);
  send(7);
  assert.equal(send.pending(), true);
  send.flush();
  send.flush();
  assert.deepEqual(sent, [7]);
  t.mock.timers.tick(1000);
  assert.deepEqual(sent, [7]);
  send(8);
  send.cancel();
  t.mock.timers.tick(1000);
  assert.deepEqual(sent, [7]);
  assert.equal(send.pending(), false);
});

test("update swaps the function that runs for the pending value", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const out = [];
  const send = debounce((v) => out.push(["old", v]), 100);
  send(1);
  send.update((v) => out.push(["new", v]));
  t.mock.timers.tick(100);
  assert.deepEqual(out, [["new", 1]]);
});
