// A small, safe Markdown subset for README / docs previews. It produces a tree (no HTML strings), which
// Markdown.jsx renders as React elements, so nothing in a document can inject markup or script.
// Supported: headings, paragraphs, bold, italic, inline code, fenced code, bullet/numbered lists,
// block quotes, rules and http(s)/relative links. Anything else shows as plain text.

const SAFE_URL = /^(https?:\/\/|\/|\.\.?\/|#|mailto:)/i;

/** Inline spans: [{t:"text"|"b"|"i"|"code"|"a", text, href?}] */
export function parseInline(src) {
  const out = [];
  let i = 0;
  let buf = "";
  const flush = () => { if (buf) { out.push({ t: "text", text: buf }); buf = ""; } };
  while (i < src.length) {
    const rest = src.slice(i);
    let m;
    if ((m = /^`([^`]+)`/.exec(rest))) { flush(); out.push({ t: "code", text: m[1] }); i += m[0].length; continue; }
    if ((m = /^\*\*([^*]+)\*\*/.exec(rest)) || (m = /^__([^_]+)__/.exec(rest))) { flush(); out.push({ t: "b", text: m[1] }); i += m[0].length; continue; }
    if ((m = /^\*([^*\s][^*]*)\*/.exec(rest)) || (m = /^_([^_\s][^_]*)_/.exec(rest))) {
      if (m[0][0] === "_" && i > 0 && /\w/.test(src[i - 1])) { buf += src[i]; i += 1; continue; }   // snake_case stays text
      flush(); out.push({ t: "i", text: m[1] }); i += m[0].length; continue;
    }
    if ((m = /^\[([^\]]+)\]\(([^)\s]+)\)/.exec(rest))) {
      flush();
      if (SAFE_URL.test(m[2])) out.push({ t: "a", text: m[1], href: m[2] });
      else out.push({ t: "text", text: m[1] });                       // javascript:, data: and friends are dropped
      i += m[0].length;
      continue;
    }
    buf += src[i];
    i += 1;
  }
  flush();
  return out;
}

/** Blocks: h, p, ul, ol, code, quote, hr. */
export function parseMarkdown(text) {
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let para = [];
  const endPara = () => { if (para.length) { blocks.push({ type: "p", inline: parseInline(para.join(" ")) }); para = []; } };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    let m;
    if ((m = /^```\s*([\w+-]*)\s*$/.exec(line))) {
      endPara();
      const code = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { code.push(lines[i]); i += 1; }
      blocks.push({ type: "code", lang: m[1], text: code.join("\n") });
      continue;
    }
    if (!line.trim()) { endPara(); continue; }
    if ((m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line))) { endPara(); blocks.push({ type: "h", level: m[1].length, inline: parseInline(m[2]) }); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { endPara(); blocks.push({ type: "hr" }); continue; }
    if ((m = /^\s*>\s?(.*)$/.exec(line))) {
      endPara();
      const prev = blocks[blocks.length - 1];
      if (prev && prev.type === "quote") prev.inline.push({ t: "text", text: " " }, ...parseInline(m[1]));
      else blocks.push({ type: "quote", inline: parseInline(m[1]) });
      continue;
    }
    if ((m = /^\s*([-*+])\s+(.*)$/.exec(line)) || (m = /^\s*(\d+)[.)]\s+(.*)$/.exec(line))) {
      endPara();
      const ordered = /\d/.test(m[1]);
      const prev = blocks[blocks.length - 1];
      if (prev && prev.type === (ordered ? "ol" : "ul")) prev.items.push(parseInline(m[2]));
      else blocks.push({ type: ordered ? "ol" : "ul", items: [parseInline(m[2])] });
      continue;
    }
    para.push(line.trim());
  }
  endPara();
  return blocks;
}
