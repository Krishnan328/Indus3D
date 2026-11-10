import { test } from "node:test";
import assert from "node:assert/strict";
import { parseInline, parseMarkdown } from "./markdownParse.js";

test("inline spans", () => {
  assert.deepEqual(parseInline("a **b** *c* `d` e"), [
    { t: "text", text: "a " }, { t: "b", text: "b" }, { t: "text", text: " " }, { t: "i", text: "c" }, { t: "text", text: " " },
    { t: "code", text: "d" }, { t: "text", text: " e" }]);
  assert.deepEqual(parseInline("snake_case_name"), [{ t: "text", text: "snake_case_name" }]);
});

test("links: only safe schemes become links", () => {
  assert.deepEqual(parseInline("[x](https://a.b/c)"), [{ t: "a", text: "x", href: "https://a.b/c" }]);
  assert.deepEqual(parseInline("[x](./docs/a.md)"), [{ t: "a", text: "x", href: "./docs/a.md" }]);
  assert.equal(parseInline("[bad](javascript:alert(1))").some((n) => n.t === "a"), false);
  assert.equal(parseInline("[bad](data:text/html;base64,AAAA)").some((n) => n.t === "a"), false);
  assert.equal(parseInline("[bad](JaVaScRiPt:x)").some((n) => n.t === "a"), false);
});

test("html in the source stays text", () => {
  const b = parseMarkdown("<script>alert(1)</script>");
  assert.deepEqual(b, [{ type: "p", inline: [{ t: "text", text: "<script>alert(1)</script>" }] }]);
});

test("blocks", () => {
  const md = "# Title\n\nHello\nworld\n\n- a\n- b\n\n1. one\n2. two\n\n> quoted\n> more\n\n---\n\n```py\nx = 1\n\ny = 2\n```\n";
  const b = parseMarkdown(md);
  assert.deepEqual(b.map((x) => x.type), ["h", "p", "ul", "ol", "quote", "hr", "code"]);
  assert.equal(b[0].level, 1);
  assert.equal(b[1].inline[0].text, "Hello world");
  assert.equal(b[2].items.length, 2);
  assert.equal(b[3].items.length, 2);
  assert.equal(b[6].text, "x = 1\n\ny = 2");
  assert.equal(b[6].lang, "py");
});

test("unterminated fence takes the rest", () => {
  assert.equal(parseMarkdown("```\na\nb").at(-1).text, "a\nb");
});
