import React from "react";
import { parseMarkdown } from "./markdownParse";

function Inline({ nodes }) {
  return nodes.map((n, i) => {
    if (n.t === "b") return <strong key={i}>{n.text}</strong>;
    if (n.t === "i") return <em key={i}>{n.text}</em>;
    if (n.t === "code") return <code key={i} className="px-1 bg-black/30 rounded font-mono text-[0.9em]">{n.text}</code>;
    if (n.t === "a") return <a key={i} href={n.href} target="_blank" rel="noopener noreferrer" className="underline text-sky-400">{n.text}</a>;
    return <React.Fragment key={i}>{n.text}</React.Fragment>;
  });
}

// Renders the safe Markdown subset from markdown.js as React elements.
export function Markdown({ text }) {
  const blocks = React.useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className="text-sm leading-relaxed space-y-3">
      {blocks.map((b, i) => {
        if (b.type === "h") {
          const sizes = ["text-2xl", "text-xl", "text-lg", "text-base", "text-sm", "text-sm"];
          return <div key={i} role="heading" aria-level={b.level} className={`font-bold ${sizes[b.level - 1]}`}><Inline nodes={b.inline} /></div>;
        }
        if (b.type === "p") return <p key={i}><Inline nodes={b.inline} /></p>;
        if (b.type === "quote") return <blockquote key={i} className="pl-3 border-l-4 border-current/30 opacity-80"><Inline nodes={b.inline} /></blockquote>;
        if (b.type === "hr") return <hr key={i} className="opacity-30" />;
        if (b.type === "code") return <pre key={i} className="p-3 overflow-auto bg-black/30 rounded font-mono text-xs">{b.text}</pre>;
        const Tag = b.type === "ol" ? "ol" : "ul";
        return <Tag key={i} className={`pl-6 space-y-1 ${b.type === "ol" ? "list-decimal" : "list-disc"}`}>{b.items.map((it, j) => <li key={j}><Inline nodes={it} /></li>)}</Tag>;
      })}
    </div>
  );
}
