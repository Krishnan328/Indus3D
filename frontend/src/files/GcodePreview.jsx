import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { API } from "../store";
import { fileUrl } from "../slices/filesSlice";
import { parseGcodeLayers, formatBytes } from "./filesLogic";
import { Btn } from "./ui";

// Top-down toolpath preview of one G-code file, drawn on a 2D canvas, layer by layer. It downloads and parses
// the whole file in the browser, so a large file asks first and a huge one is refused.
export const LARGE_PREVIEW_BYTES = 8 * 1024 * 1024;
export const MAX_PREVIEW_BYTES = 80 * 1024 * 1024;

export function GcodePreview({ root, path, size }) {
  const needsConfirm = (size || 0) > LARGE_PREVIEW_BYTES;
  const tooBig = (size || 0) > MAX_PREVIEW_BYTES;
  const [go, setGo] = useState(!needsConfirm);
  const [state, setState] = useState({ phase: "idle", error: null, data: null });
  const [layer, setLayer] = useState(0);
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!go || tooBig) return undefined;
    let alive = true;
    (async () => {
      try {
        const res = await fetch(fileUrl(API, root, path));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (!alive) return;
        const data = parseGcodeLayers(text);
        setState({ phase: "ready", error: null, data });
        setLayer(Math.max(0, data.layers.length - 1));
      } catch (e) {
        if (alive) setState({ phase: "error", error: String(e.message || e), data: null });
      }
    })();
    return () => { alive = false; };
  }, [go, tooBig, root, path]);

  const data = state.data;
  const box = useMemo(() => {
    if (!data) return null;
    const { minX, maxX, minY, maxY } = data.bounds;
    return { minX, minY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) };
  }, [data]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !data || !box) return;
    const ctx = cv.getContext("2d");
    const W = cv.width;
    const H = cv.height;
    ctx.clearRect(0, 0, W, H);
    const pad = 12;
    const scale = Math.min((W - 2 * pad) / box.w, (H - 2 * pad) / box.h);
    const px = (x) => pad + (x - box.minX) * scale;
    const py = (y) => H - pad - (y - box.minY) * scale;
    const draw = (segs, style, width) => {
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.beginPath();
      for (let i = 0; i < segs.length; i += 4) {
        ctx.moveTo(px(segs[i]), py(segs[i + 1]));
        ctx.lineTo(px(segs[i + 2]), py(segs[i + 3]));
      }
      ctx.stroke();
    };
    const from = Math.max(0, layer - 3);
    for (let i = from; i < layer; i += 1) draw(data.layers[i].segs, `rgba(120,160,220,${0.15 + 0.1 * (i - from)})`, 1);
    if (data.layers[layer]) draw(data.layers[layer].segs, "#34d399", 1.4);
  }, [data, box, layer]);

  if (tooBig) {
    return <div className="p-3 text-xs flex gap-2 items-start text-amber-400"><AlertTriangle size={14} className="shrink-0" />
      This file ({formatBytes(size)}) is too large to preview in the browser. Download it and open it in a slicer instead.</div>;
  }
  if (!go) {
    return (
      <div className="p-3 text-xs space-y-2 border border-amber-500/40 rounded">
        <div className="flex gap-2 items-start text-amber-400"><AlertTriangle size={14} className="shrink-0" />
          <span>This file is {formatBytes(size)}. Loading it for a preview downloads all of it and may take a while and a lot of memory on a small device.</span></div>
        <Btn onClick={() => setGo(true)}>Load preview anyway</Btn>
      </div>
    );
  }
  if (state.phase === "error") return <div className="p-3 text-xs text-red-400">Could not load the file: {state.error}</div>;
  if (state.phase !== "ready") return <div className="p-3 text-xs opacity-60">Reading and parsing G-code…</div>;
  if (!data.layers.length) return <div className="p-3 text-xs opacity-60">No extruding moves found in this file.</div>;
  const cur = data.layers[layer];
  return (
    <div className="space-y-2">
      <canvas ref={canvasRef} width={520} height={380} className="w-full max-w-[520px] bg-black/30 rounded" role="img"
        aria-label={`Toolpath of layer ${layer + 1} of ${data.layers.length}`} />
      <div className="flex items-center gap-3 text-xs">
        <label htmlFor="layer-slider" className="shrink-0">Layer {layer + 1} / {data.layers.length}</label>
        <input id="layer-slider" type="range" min={0} max={data.layers.length - 1} value={layer} onChange={(e) => setLayer(Number(e.target.value))} className="flex-1" />
        <span className="opacity-60 shrink-0">Z {cur?.z?.toFixed(2)}</span>
      </div>
      {data.truncated && <div className="text-[11px] text-amber-400">Preview truncated: only the first part of the file is drawn.</div>}
    </div>
  );
}
