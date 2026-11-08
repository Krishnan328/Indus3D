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
import { useIsBrutalist } from "./theme";

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
function AxisCard({ label, data, history, brutalist = false }) {
  if (!data) return null;
  const { rms = 0, peak_hz = 0, kurtosis = 0 } = data;

  return (
    <div style={{
      background: brutalist ? "#ffffff" : "#1e293b",
      border: brutalist ? "2px solid #111" : "none",
      borderRadius: brutalist ? 0 : 8,
      padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 140,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 700, color: brutalist ? "#111" : "#e2e8f0", fontSize: 13 }}>{label}-axis</span>
        <span style={{ fontSize: 11, color: rmsColor(rms), fontWeight: 600 }}>
          {rms.toFixed(3)} g
        </span>
      </div>

      {/* RMS bar */}
      <div style={{ background: brutalist ? "#f1f5f9" : "#0f172a", border: brutalist ? "1px solid #111" : "none", borderRadius: brutalist ? 0 : 4, height: 6, overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: `${Math.min(100, (rms / 1.0) * 100)}%`,
          background: rmsColor(rms),
          transition: "width 0.3s ease",
        }} />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: brutalist ? "#64748b" : "#94a3b8" }}>
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
  const brutalist = useIsBrutalist?.() || false;

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

  const dspOnline = Boolean(vibration?.dsp_online ?? vibration?.available);
  const isStreaming = Boolean(vibration?.streaming || ((vibration?.x?.rms ?? 0) > 0 || (vibration?.y?.rms ?? 0) > 0 || (vibration?.z?.rms ?? 0) > 0));

  return (
    <div style={{
      background: brutalist ? "#ffffff" : "#0f172a",
      border: brutalist ? "3px solid #111" : "1px solid #1e293b",
      borderRadius: brutalist ? 0 : 10,
      padding: "14px 16px",
      color: brutalist ? "#111" : "#e2e8f0",
      fontFamily: "monospace",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 15 }}>📳</span>
        <span style={{ fontWeight: 700, fontSize: 14, color: brutalist ? "#111" : "#f1f5f9" }}>
          Vibration Monitor
        </span>
        <span style={{
          marginLeft: "auto", fontSize: 10, padding: "2px 6px",
          borderRadius: 4,
          background: !dspOnline
            ? (brutalist ? "#ffe4e6" : "#1e293b")
            : isStreaming
              ? (brutalist ? "#bbf7d0" : "#14532d")
              : (brutalist ? "#dbeafe" : "#1e3a8a"),
          color: !dspOnline
            ? "#ef4444"
            : isStreaming
              ? (brutalist ? "#14532d" : "#86efac")
              : (brutalist ? "#1e3a8a" : "#93c5fd"),
          fontWeight: 700,
          border: brutalist ? "2px solid #111" : "none",
        }}>
          {!dspOnline ? "DSP OFFLINE" : isStreaming ? "LIVE" : "STANDBY"}
        </span>
      </div>

      {!dspOnline ? (
        <div style={{ color: "#64748b", fontSize: 12, textAlign: "center", padding: "16px 0" }}>
          DSP pipeline in standby or reconnecting.<br />
          <code style={{ fontSize: 11, color: "#94a3b8" }}>Listening for ADXL345 / Klipper stream on UDP :3201</code>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <AxisCard label="X" data={vibration?.x || { rms: 0, peak_hz: 0, kurtosis: 0 }} history={history.x} brutalist={brutalist} />
            <AxisCard label="Y" data={vibration?.y || { rms: 0, peak_hz: 0, kurtosis: 0 }} history={history.y} brutalist={brutalist} />
            <AxisCard label="Z" data={vibration?.z || { rms: 0, peak_hz: 0, kurtosis: 0 }} history={history.z} brutalist={brutalist} />
          </div>

          {vibration?.auto_z && (
            <div style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "6px 10px",
              borderRadius: 6,
              background: brutalist ? "#f8fafc" : "rgba(15, 23, 42, 0.6)",
              border: brutalist ? "1px solid #111" : "1px solid rgba(148, 163, 184, 0.15)",
              fontSize: 11,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: vibration.auto_z.regime === "rubbing" ? "#ef4444" : vibration.auto_z.regime === "under_squish" ? "#f59e0b" : "#10b981",
                  boxShadow: `0 0 6px ${vibration.auto_z.regime === "rubbing" ? "#ef4444" : vibration.auto_z.regime === "under_squish" ? "#f59e0b" : "#10b981"}`,
                }} />
                <span style={{ fontWeight: 600, color: brutalist ? "#111" : "#e2e8f0" }}>
                  Bed Friction (HFFI):
                </span>
                <span style={{ fontFamily: "monospace", color: brutalist ? "#0284c7" : "#38bdf8" }}>
                  {(vibration.auto_z.hffi ?? 0).toFixed(2)}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{
                  padding: "2px 6px",
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  background: vibration.auto_z.regime === "rubbing" ? "rgba(239, 68, 68, 0.15)" : vibration.auto_z.regime === "under_squish" ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
                  color: vibration.auto_z.regime === "rubbing" ? "#ef4444" : vibration.auto_z.regime === "under_squish" ? "#f59e0b" : "#10b981",
                }}>
                  {vibration.auto_z.regime === "rubbing" ? "Nozzle Rubbing" : vibration.auto_z.regime === "under_squish" ? "Under-Squish" : "Optimal Squish"}
                </span>
                {vibration.auto_z.recommended_trim !== 0 && (
                  <span style={{ fontFamily: "monospace", color: "#f59e0b", fontSize: 10 }}>
                    Trim: {vibration.auto_z.recommended_trim > 0 ? `+${vibration.auto_z.recommended_trim.toFixed(3)}` : vibration.auto_z.recommended_trim.toFixed(3)}mm
                  </span>
                )}
              </div>
            </div>
          )}
          {!isStreaming && (
            <div style={{ fontSize: 10, color: "#64748b", textAlign: "center", marginTop: 4 }}>
              DSP pipeline active (UDP:3200) · Ready for accelerometer telemetry during print
            </div>
          )}
        </div>
      )}
    </div>
  );
}
