/**
 * VibrationPanel.jsx
 * -------------------
 * Displays live accelerometer / FFT data from the Rust DSP pipeline.
 * Shows per-axis RMS gauges, peak frequency, kurtosis, and a 60-second
 * RMS history sparkline. Falls back gracefully when the DSP binary is
 * not available (vibration === null or available === false).
 */

import React, { useState, useEffect, useRef } from "react";
import { useStore } from "./store";

// ── Colour helpers ─────────────────────────────────────────────────────────
function rmsColor(rms) {
  if (rms > 0.8) return "#ef4444"; // red — critical
  if (rms > 0.3) return "#f59e0b"; // amber — warn
  return "#22c55e";                 // green — ok
}

function kurtosisColor(k) {
  if (k > 5) return "#f59e0b";
  return "#94a3b8";
}

// ── Sparkline (60-sample canvas) ──────────────────────────────────────────
function Sparkline({ data, color = "#06b6d4" }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data || data.length < 2) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    const max = Math.max(...data, 0.01);
    const step = w / (data.length - 1);

    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    data.forEach((v, i) => {
      const x = i * step;
      const y = h - (v / max) * h * 0.9;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  }, [data, color]);

  return (
    <canvas
      ref={canvasRef}
      width={180}
      height={32}
      style={{ display: "block", borderRadius: 4, background: "#0f172a" }}
    />
  );
}

// ── Single axis card ──────────────────────────────────────────────────────
function AxisCard({ label, data, history }) {
  if (!data) return null;
  const { rms = 0, peak_hz = 0, kurtosis = 0 } = data;

  return (
    <div style={{
      background: "#1e293b", borderRadius: 8, padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 140,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 700, color: "#e2e8f0", fontSize: 13 }}>{label}-axis</span>
        <span style={{ fontSize: 11, color: rmsColor(rms), fontWeight: 600 }}>
          {rms.toFixed(3)} g
        </span>
      </div>

      {/* RMS bar */}
      <div style={{ background: "#0f172a", borderRadius: 4, height: 6, overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: `${Math.min(100, (rms / 1.0) * 100)}%`,
          background: rmsColor(rms),
          transition: "width 0.3s ease",
        }} />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#94a3b8" }}>
        <span>{peak_hz.toFixed(1)} Hz</span>
        <span style={{ color: kurtosisColor(kurtosis) }}>K={kurtosis.toFixed(1)}</span>
      </div>

      {history && history.length > 1 && (
        <Sparkline data={history} color={rmsColor(rms)} />
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────
export function VibrationPanel() {
  const vibration = useStore((s) => s.vibration);

  // 60-second RMS history per axis, stored in state so it renders correctly
  const [history, setHistory] = useState({ x: [], y: [], z: [] });

  useEffect(() => {
    if (!vibration?.available) return;
    setHistory(prev => ({
      x: [...prev.x, vibration.x?.rms ?? 0].slice(-60),
      y: [...prev.y, vibration.y?.rms ?? 0].slice(-60),
      z: [...prev.z, vibration.z?.rms ?? 0].slice(-60),
    }));
  }, [vibration]);

  const unavailable = !vibration || !vibration.available;

  return (
    <div style={{
      background: "#0f172a",
      border: "1px solid #1e293b",
      borderRadius: 10,
      padding: "14px 16px",
      color: "#e2e8f0",
      fontFamily: "monospace",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 15 }}>📳</span>
        <span style={{ fontWeight: 700, fontSize: 14, color: "#f1f5f9" }}>
          Vibration Monitor
        </span>
        <span style={{
          marginLeft: "auto", fontSize: 10, padding: "2px 6px",
          borderRadius: 4,
          background: unavailable ? "#1e293b" : "#14532d",
          color: unavailable ? "#475569" : "#86efac",
          fontWeight: 600,
        }}>
          {unavailable ? "DSP OFFLINE" : "LIVE"}
        </span>
      </div>

      {unavailable ? (
        <div style={{ color: "#475569", fontSize: 12, textAlign: "center", padding: "16px 0" }}>
          Rust DSP binary not running.<br />
          <code style={{ fontSize: 11 }}>cd backend/dsp &amp;&amp; cargo build --release</code>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <AxisCard label="X" data={vibration.x} history={history.x} />
          <AxisCard label="Y" data={vibration.y} history={history.y} />
          <AxisCard label="Z" data={vibration.z} history={history.z} />
        </div>
      )}
    </div>
  );
}
