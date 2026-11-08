import React, { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

// uPlot canvas for the temperature chart. This module is imported lazily (React.lazy in TemperatureChart),
// so uPlot only ships when a dashboard actually shows the chart.
//
//   x, ys      aligned data (see thermalLogic.align): shared timestamps and one column per series
//   defs       [{id, label, color, dashed, axis: "temp" | "pct"}] in the same order as ys
//   hidden     {id: true} series that are switched off
//   focusId    series highlighted from outside (legend hover); onFocus(id|null) reports plot hover
//   ceiling    top of the temperature axis
// Drag on the plot to zoom, double-click (or the button) to reset. While zoomed, new live data does not
// move the view.

// "rgb(r, g, b)" / "#rrggbb" -> rgba with alpha (CSS colours cannot take a hex-alpha suffix after rgb()).
function fade(color, alpha) {
  const m = /rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(color);
  if (m) return `rgba(${m[1]},${m[2]},${m[3]},${alpha})`;
  const h = /^#([0-9a-f]{6})$/i.exec(color);
  if (h) { const n = parseInt(h[1], 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${alpha})`; }
  return `rgba(128,128,128,${alpha})`;
}

const fmtTemp = (u, vals) => vals.map((v) => `${v}°`);
const fmtPct = (u, vals) => vals.map((v) => `${v}%`);

export default function ThermalPlot({ x, ys, defs, hidden, focusId, onFocus, ceiling, spanS }) {
  const host = useRef(null);
  const tip = useRef(null);
  const plot = useRef(null);
  const latest = useRef({ ceiling, defs, hidden, onFocus, x, ys, spanS });
  const zoomed = useRef(false);
  const [isZoomed, setIsZoomed] = useState(false);

  useEffect(() => { latest.current = { ceiling, defs, hidden, onFocus, x, ys, spanS }; });

  const signature = defs.map((d) => `${d.id}|${d.color}|${d.axis}|${d.dashed ? 1 : 0}`).join(";");
  const hasPct = defs.some((d) => d.axis === "pct");

  // (Re)build the plot when the series set or their look changes.
  useEffect(() => {
    const el = host.current;
    if (!el) return undefined;
    const ink = getComputedStyle(el).color || "#888";
    const grid = { stroke: fade(ink, 0.13), width: 1 };
    const opts = {
      width: el.clientWidth || 300, height: el.clientHeight || 160,
      padding: [8, 6, 0, 0], legend: { show: false },
      cursor: { drag: { x: true, y: false, setScale: true }, focus: { prox: 28 }, points: { size: 6 } },
      focus: { alpha: 0.25 },
      scales: {
        x: { time: true },
        temp: { range: () => [0, latest.current.ceiling] },
        pct: { range: () => [0, 100] },
      },
      axes: [
        { stroke: ink, grid, ticks: { stroke: grid.stroke }, font: "10px sans-serif", size: 28 },
        { scale: "temp", stroke: ink, grid, ticks: { stroke: grid.stroke }, font: "10px sans-serif", size: 38, values: fmtTemp },
        { scale: "pct", side: 1, show: hasPct, stroke: ink, grid: { show: false }, ticks: { stroke: grid.stroke }, font: "10px sans-serif", size: 38, values: fmtPct },
      ],
      series: [{}, ...defs.map((d) => ({
        label: d.label, scale: d.axis, stroke: d.color, width: d.dashed ? 1.4 : 2, dash: d.dashed ? [6, 4] : undefined,
        spanGaps: true, points: { show: false }, show: !latest.current.hidden[d.id],
      }))],
      hooks: {
        setSeries: [(u, idx, o) => {
          if (o && "focus" in o) latest.current.onFocus?.(idx == null ? null : latest.current.defs[idx - 1]?.id ?? null);
        }],
        // Zoomed = the visible x range differs from the window we would show by ourselves.
        setScale: [(u, key) => {
          if (key !== "x") return;
          const { x: xs, spanS: span } = latest.current;
          if (xs.length < 2) return;
          const hi = xs[xs.length - 1];
          const lo = Math.max(xs[0], hi - (span || Infinity));
          const tol = Math.max(1.5, ((span || hi - xs[0]) * 0.01));
          const now = Math.abs(u.scales.x.min - lo) > tol || Math.abs(u.scales.x.max - hi) > tol;
          if (now !== zoomed.current) { zoomed.current = now; setIsZoomed(now); }
        }],
        setCursor: [(u) => {
          const box = tip.current;
          if (!box) return;
          const i = u.cursor.idx;
          if (i == null || u.cursor.left < 0) { box.style.display = "none"; return; }
          const { defs: ds, hidden: hid, ys: cols, x: xs } = latest.current;
          const rows = [];
          ds.forEach((d, k) => {
            const v = cols[k]?.[i];
            if (v == null || hid[d.id]) return;
            rows.push(`<div style="display:flex;gap:6px;align-items:center"><i style="width:8px;height:8px;border-radius:50%;background:${d.color};display:inline-block"></i><span style="opacity:.7">${d.label.replace(/[<>&]/g, "")}</span><b style="margin-left:auto">${v.toFixed(1)}${d.axis === "pct" ? "%" : "°"}</b></div>`);
          });
          const when = new Date(xs[i] * 1000).toLocaleTimeString();
          box.innerHTML = `<div style="opacity:.6;margin-bottom:2px">${when}</div>${rows.slice(0, 10).join("")}`;
          box.style.display = "block";
          const w = u.root.clientWidth;
          box.style.left = `${u.cursor.left > w / 2 ? Math.max(0, u.cursor.left - box.offsetWidth - 12) : u.cursor.left + 14}px`;
        }],
      },
    };
    const u = new uPlot(opts, [latest.current.x, ...latest.current.ys], el);
    plot.current = u;
    zoomed.current = false;
    setIsZoomed(false);
    const ro = new ResizeObserver(() => u.setSize({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
    return () => { ro.disconnect(); u.destroy(); plot.current = null; };
  }, [signature, hasPct]);   // eslint-disable-line react-hooks/exhaustive-deps -- rebuilt only when the series' look changes; data flows through setData

  // New data: keep the view if the user zoomed, otherwise show the newest `spanS` seconds.
  useEffect(() => {
    const u = plot.current;
    if (!u) return;
    u.setData([x, ...ys], false);
    if (!zoomed.current && x.length > 1) {
      const hi = x[x.length - 1];
      u.setScale("x", { min: Math.max(x[0], hi - (spanS || Infinity)), max: hi });
    }
  }, [x, ys, spanS, ceiling, signature]);

  // Hide / show without rebuilding.
  useEffect(() => {
    const u = plot.current;
    if (!u) return;
    defs.forEach((d, i) => { const want = !hidden[d.id]; if (u.series[i + 1] && u.series[i + 1].show !== want) u.setSeries(i + 1, { show: want }); });
  }, [hidden, defs, signature]);

  // Highlight from the legend.
  useEffect(() => {
    const u = plot.current;
    if (!u) return;
    const idx = focusId ? defs.findIndex((d) => d.id === focusId) + 1 : null;
    u.setSeries(idx && idx > 0 ? idx : null, { focus: true }, false);
  }, [focusId, defs, signature]);

  const reset = () => {
    const u = plot.current;
    if (!u || x.length < 2) return;
    zoomed.current = false; setIsZoomed(false);
    u.setScale("x", { min: Math.max(x[0], x[x.length - 1] - (spanS || Infinity)), max: x[x.length - 1] });
  };

  return (
    <div className="relative w-full h-full min-h-[120px]">
      <div ref={host} className="absolute inset-0" onDoubleClick={reset} data-testid="thermal-plot" />
      <div ref={tip} className="pointer-events-none absolute top-1 z-10 hidden rounded border border-current/20 bg-black/80 px-2 py-1 text-[10px] font-mono text-gray-100 shadow" style={{ minWidth: 120 }} />
      {isZoomed && <button onClick={reset} className="absolute top-1 right-1 z-10 rounded bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white">Reset zoom</button>}
    </div>
  );
}
