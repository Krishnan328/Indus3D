#!/usr/bin/env python3
"""
Indus3D Smart Filament Sensor Host Daemon
=========================================
Bridge between the RP2040 Smart Filament Sensor (USB) and Klipper / Moonraker.

Key Capabilities:
1. True Volumetric Flow & Auto-Flow Multiplier:
   - Maintains a FIFO delay buffer matching the Bowden tube length.
   - Adjusts Klipper's M221 flow rate dynamically as diameter variations reach the nozzle.
2. Material & Spool Weight Tracking:
   - Integrates linear volume and multiplies by material density (PLA, ABS, PETG, TPU, etc.).
   - Computes live grams used and remaining spool capacity.
3. Zero-Waste Smart Runout:
   - When filament exits the sensor, counts down the remaining Bowden length.
   - Triggers SMART_RUNOUT_PAUSE just before the filament tip leaves the extruder gears.
4. Clog & Slip Watchdog:
   - Detects when the extruder is feeding but filament motion stalls or lags.
   - Triggers an immediate safe pause before the drive gear grinds the filament.
5. Local REST API:
   - Exposes http://127.0.0.1:7126/status for the Indus3D Web UI / Dashboard.
"""

import sys
import os
import time
import math
import glob
import json
import struct
import select
import signal
import logging
import threading
import configparser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
try:
    import serial
except ImportError:
    serial = None

# Default Material Densities (g/cm³)
MATERIAL_DENSITIES = {
    "PLA": 1.24,
    "PLA-CF": 1.25,
    "PETG": 1.27,
    "PETG-CF": 1.29,
    "ABS": 1.04,
    "ASA": 1.07,
    "TPU": 1.21,
    "PA": 1.14,
    "PA-CF": 1.18,
    "PC": 1.20,
    "PVA": 1.23,
    "HIPS": 1.04
}

CONFIG_FILE_DEFAULT = "indus3d_sensor.ini"
STATE_FILE_DEFAULT = ".indus3d_spool_state.json"

DEFAULT_INI = """# =====================================================================
# Indus3D Smart Filament Sensor Configuration
# =====================================================================

[sensor]
# Serial port for RP2040 Pico. Leave empty for auto-detection.
# Example: /dev/serial/by-id/usb-Raspberry_Pi_Pico_E6614103E72F8E23-if00
port = 
baud = 115200

[bowden]
# Distance from the sensor exit collet to the extruder drive gears in mm.
# Measure by marking filament at extruder entrance and measuring to sensor exit.
bowden_length_mm = 650.0

# Safe margin (mm) left in front of extruder drive gears during runout pause.
# Prevents filament tip from getting lost inside the gears.
runout_margin_mm = 40.0

[spool]
# Material type (PLA, PETG, ABS, ASA, TPU, PA-CF, etc.)
material = PLA

# Custom material density in g/cm3 (set to 0.0 to use default for selected material)
density_g_cm3 = 0.0

# Total starting filament weight in grams
initial_spool_weight_g = 1000.0

[features]
# Dynamic Auto-Flow Multiplier (M221):
# Modulates extrusion flow rate based on measured filament diameter.
enable_auto_flow = true

# Update frequency: minimum distance (mm) extruded between M221 adjustments
flow_update_interval_mm = 50.0

# Safe clamp bounds for M221 flow percentage
min_flow_percent = 85.0
max_flow_percent = 115.0

# Extruder Slip / Clog Protection:
# Pauses print if extruder motor is feeding but filament sensor is stationary
enable_clog_detection = true
slip_threshold_ratio = 0.40
slip_timeout_seconds = 1.5

[moonraker]
# URL of Moonraker API on local Klipper host
url = http://127.0.0.1:7125
api_key = 

[api]
# Address the status/control server listens on. Keep 127.0.0.1: the control
# endpoints have no authentication, and Indus3D reaches the daemon locally
# (its own authenticated API proxies the actions). Use 0.0.0.0 only on a
# network you fully trust.
host = 127.0.0.1
# Local HTTP server port for Indus3D Web UI telemetry
port = 7126
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Indus3D Smart Filament Sensor</title>
<style>
  :root {
    --bg: #090d16;
    --card-bg: #111827;
    --card-border: #1f2937;
    --text-main: #f9fafb;
    --text-muted: #9ca3af;
    --cyan: #06b6d4;
    --emerald: #10b981;
    --amber: #f59e0b;
    --rose: #f43f5e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background-color: var(--bg);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    padding: 24px 20px;
    min-height: 100vh;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--card-border);
    flex-wrap: wrap;
    gap: 12px;
  }
  .header-left h1 {
    font-size: 1.45rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .header-left p {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-top: 2px;
  }
  .status-badges { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .badge {
    padding: 5px 12px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .badge-connected { background: rgba(16, 185, 129, 0.15); color: var(--emerald); border: 1px solid rgba(16, 185, 129, 0.3); }
  .badge-disconnected { background: rgba(244, 63, 94, 0.15); color: var(--rose); border: 1px solid rgba(244, 63, 94, 0.3); }
  .badge-rate { background: rgba(6, 182, 212, 0.15); color: var(--cyan); border: 1px solid rgba(6, 182, 212, 0.3); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
    gap: 18px;
    margin-bottom: 24px;
  }
  .card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 14px;
    padding: 20px;
    position: relative;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
  }
  .card-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .card-value {
    font-size: 2.1rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
    margin-bottom: 4px;
  }
  .card-unit { font-size: 0.95rem; font-weight: 500; color: var(--text-muted); margin-left: 4px; }
  .card-meta {
    font-size: 0.85rem;
    color: var(--text-muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
  }
  .pill {
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
  }
  .pill-extrude { background: rgba(16, 185, 129, 0.2); color: var(--emerald); }
  .pill-retract { background: rgba(245, 158, 11, 0.2); color: var(--amber); }
  .pill-idle { background: rgba(156, 163, 175, 0.2); color: var(--text-muted); }
  .pill-loaded { background: rgba(16, 185, 129, 0.2); color: var(--emerald); }
  .pill-empty { background: rgba(244, 63, 94, 0.2); color: var(--rose); animation: pulse 1s infinite alternate; }
  @keyframes pulse { from { opacity: 0.7; } to { opacity: 1; } }
  .bar-container {
    width: 100%;
    height: 8px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 10px;
  }
  .bar-fill {
    height: 100%;
    background: var(--cyan);
    border-radius: 4px;
    transition: width 0.15s ease, background-color 0.2s ease;
  }
  .chart-section {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 24px;
  }
  .chart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }
  .chart-legend { display: flex; gap: 16px; font-size: 0.8rem; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-color { width: 10px; height: 10px; border-radius: 2px; }
  canvas {
    width: 100%;
    height: 220px;
    display: block;
    background: #090e18;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
  .btn {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: var(--text-main);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 0.75rem;
    cursor: pointer;
    font-weight: 500;
  }
  .btn:hover { background: rgba(255, 255, 255, 0.15); }
  .alert-banner {
    background: rgba(244, 63, 94, 0.15);
    border: 1px solid var(--rose);
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 20px;
    display: none;
    align-items: center;
    justify-content: space-between;
    color: #fecdd3;
  }
  footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--text-muted);
    font-size: 0.8rem;
    padding-top: 16px;
    border-top: 1px solid var(--card-border);
  }
  footer a { color: var(--cyan); text-decoration: none; }
  footer a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <div id="runout-banner" class="alert-banner">
    <div>⚠️ <strong>RUNOUT DETECTED:</strong> Filament has left the sensor. Printing remaining Bowden buffer (<span id="runout-remain-banner">0</span> mm remaining).</div>
  </div>

  <header>
    <div class="header-left">
      <h1>Indus3D Smart Filament Sensor</h1>
      <p>Sub-millimeter motion tracking, diameter auto-flow, & zero-waste runout</p>
    </div>
    <div class="status-badges">
      <div id="conn-badge" class="badge badge-connected">
        <span class="dot"></span>
        <span id="conn-text">CONNECTED (<span id="port-name">--</span>)</span>
      </div>
      <div class="badge badge-rate">10 Hz LIVE AUTO-REFRESH</div>
    </div>
  </header>

  <div class="grid">
    <!-- Card 1: Stroke & Velocity -->
    <div class="card">
      <div class="card-label">
        <span>Filament Stroke</span>
        <span id="dir-pill" class="pill pill-idle">IDLE</span>
      </div>
      <div class="card-value">
        <span id="val-pos">0.0</span><span class="card-unit">mm</span>
      </div>
      <div class="card-meta">
        <span>Speed: <strong id="val-spd">+0.0</strong> mm/s</span>
        <span>Flow: <strong id="val-flow-vol">0.0</strong> mm³/s</span>
      </div>
    </div>

    <!-- Card 2: Diameter & Bowden FIFO -->
    <div class="card">
      <div class="card-label">
        <span>Filament Diameter</span>
        <div style="display:flex; gap:6px;">
          <button class="btn" onclick="tareEmpty()" title="Zero empty bearings baseline when no filament is loaded">Tare Empty (0mm)</button>
          <button class="btn" onclick="calibrateSpan()" title="Calibrate span scale with 1.75mm filament loaded">Calibrate 1.75mm</button>
          <button class="btn" onclick="resetBowden()" title="Clear Bowden tube pre-measured diameter buffer">Flush Tube</button>
        </div>
      </div>
      <div class="card-value">
        <span id="val-dia">1.750</span><span class="card-unit">mm</span>
      </div>
      <div class="card-meta">
        <span>At Nozzle: <strong id="val-nozzle-dia">1.750</strong> mm</span>
        <span id="dia-dev">±0.000 mm</span>
      </div>
      <div class="card-meta" style="margin-top: 6px; padding-top: 6px;">
        <span>Raw Angle: <strong id="val-raw-dia">--</strong></span>
        <span>Tube: <strong id="val-tube-mem">0.0</strong> mm</span>
        <span id="tube-pill" class="pill pill-idle">EMPTY</span>
      </div>
    </div>

    <!-- Card 3: Auto-Flow Multiplier -->
    <div class="card">
      <div class="card-label">
        <span>Auto-Flow Multiplier</span>
        <span>M221 Target</span>
      </div>
      <div class="card-value">
        <span id="val-flow-pct">100.0</span><span class="card-unit">%</span>
      </div>
      <div class="bar-container">
        <div id="flow-bar" class="bar-fill" style="width: 50%;"></div>
      </div>
      <div class="card-meta">
        <span>Min: 85%</span>
        <span>Nominal: 100%</span>
        <span>Max: 115%</span>
      </div>
    </div>

    <!-- Card 4: Spool Weight Manager -->
    <div class="card">
      <div class="card-label">
        <span>Spool Remaining</span>
        <button class="btn" onclick="resetSpool()">Reset (0g)</button>
      </div>
      <div class="card-value">
        <span id="val-spool-rem">1000.0</span><span class="card-unit">g</span>
      </div>
      <div class="bar-container">
        <div id="spool-bar" class="bar-fill" style="width: 100%; background: var(--emerald);"></div>
      </div>
      <div class="card-meta">
        <span>Used: <strong id="val-spool-used">0.0</strong> g</span>
        <span>Material: <strong id="val-mat">PLA</strong></span>
      </div>
    </div>

    <!-- Card 5: Filament Switch & Runout Buffer -->
    <div class="card">
      <div class="card-label">
        <span>Switch State</span>
        <span id="switch-pill" class="pill pill-idle">CHECKING...</span>
      </div>
      <div class="card-value">
        <span id="val-runout-buf">--</span>
      </div>
      <div class="card-meta">
        <span>Buffer Remaining: <strong id="val-runout-mm">0.0</strong> mm</span>
        <span id="val-runout-status">--</span>
      </div>
    </div>

    <!-- Card 6: Peak Metrics -->
    <div class="card">
      <div class="card-label">
        <span>Session Peaks</span>
        <span>Max Tested</span>
      </div>
      <div style="margin-top: 8px; font-size: 0.9rem; line-height: 1.6;">
        <div>Max Extrude: <strong id="peak-extrude" style="color:var(--emerald);">0.0</strong> mm/s</div>
        <div>Max Retract: <strong id="peak-retract" style="color:var(--amber);">0.0</strong> mm/s</div>
        <div>Max Flow: <strong id="peak-flow" style="color:var(--cyan);">0.0</strong> mm³/s</div>
      </div>
    </div>
  </div>

  <!-- Real-Time Oscilloscope / Chart -->
  <div class="chart-section">
    <div class="chart-header">
      <h2 style="font-size:1.1rem; font-weight:600;">Real-Time Dynamics (Last 15 Seconds)</h2>
      <div class="chart-legend">
        <div class="legend-item">
          <div class="legend-color" style="background: var(--cyan);"></div>
          <span>Speed (mm/s)</span>
        </div>
        <div class="legend-item">
          <div class="legend-color" style="background: var(--amber);"></div>
          <span>Diameter (mm)</span>
        </div>
      </div>
    </div>
    <canvas id="chart"></canvas>
  </div>

  <footer>
    <div>Indus3D Ecosystem &bull; Firmware: 1000 Hz Silicon Fast-Filter &bull; RP2040</div>
    <div><a href="/status" target="_blank">View Raw JSON (/status)</a></div>
  </footer>
</div>

<script>
  const history = [];
  const MAX_HISTORY = 150;
  const canvas = document.getElementById('chart');
  const ctx = canvas.getContext('2d');

  const ACTION_HEADERS = {'X-Indus3D-Action': '1'};  // control endpoints require this header

  function resizeCanvas() {
    canvas.width = canvas.parentElement.clientWidth - 40;
    canvas.height = 220;
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  async function poll() {
    try {
      const res = await fetch('/status');
      if (!res.ok) throw new Error();
      const data = await res.json();
      render(data);
    } catch (e) {
      document.getElementById('conn-badge').className = 'badge badge-disconnected';
      document.getElementById('conn-text').textContent = 'DISCONNECTED';
    }
  }

  const setText = (id, txt) => {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  };

  function render(data) {
    const badge = document.getElementById('conn-badge');
    if (badge) badge.className = data.connected ? 'badge badge-connected' : 'badge badge-disconnected';
    setText('conn-text', data.connected ? 'CONNECTED (' + (data.port || 'USB') + ')' : 'DISCONNECTED');

    setText('val-pos', data.position_mm.toFixed(1));
    const spd = data.velocity_mm_s;
    setText('val-spd', (spd >= 0 ? '+' : '') + spd.toFixed(1));
    setText('val-flow-vol', data.volumetric_flow_mm3_s.toFixed(1));

    const dirPill = document.getElementById('dir-pill');
    if (dirPill) {
      if (spd > 0.4) {
        dirPill.className = 'pill pill-extrude';
        dirPill.textContent = 'EXTRUDING';
      } else if (spd < -0.4) {
        dirPill.className = 'pill pill-retract';
        dirPill.textContent = 'RETRACTING';
      } else {
        dirPill.className = 'pill pill-idle';
        dirPill.textContent = 'IDLE';
      }
    }

    const dia = data.diameter_mm;
    setText('val-dia', dia.toFixed(3));
    setText('val-nozzle-dia', data.nozzle_diameter_mm.toFixed(3));
    setText('val-raw-dia', data.raw_dia_angle || '--');
    const diff = dia - 1.750;
    const diffPct = (diff / 1.750) * 100;
    const diffSign = diff >= 0 ? '+' : '';
    setText('dia-dev', `${diffSign}${diff.toFixed(3)} mm (${diffSign}${diffPct.toFixed(1)}%)`);

    // Bowden Tube Buffer Memory
    const tubeMem = data.bowden_buffered_mm || 0;
    setText('val-tube-mem', tubeMem.toFixed(1));
    const tubePill = document.getElementById('tube-pill');
    if (tubePill) {
      if (data.bowden_restored) {
        tubePill.className = 'pill pill-loaded';
        tubePill.textContent = 'RESTORED (' + (data.bowden_avg_dia_mm || 1.75).toFixed(3) + 'mm)';
      } else if (tubeMem > 10) {
        tubePill.className = 'pill pill-extrude';
        tubePill.textContent = 'MAPPED (' + (data.bowden_avg_dia_mm || 1.75).toFixed(3) + 'mm)';
      } else {
        tubePill.className = 'pill pill-idle';
        tubePill.textContent = 'EMPTY';
      }
    }

    const flowPct = data.auto_flow_percent;
    setText('val-flow-pct', flowPct.toFixed(1));
    const flowBar = document.getElementById('flow-bar');
    if (flowBar) {
      const barW = Math.max(0, Math.min(100, ((flowPct - 85) / 30) * 100));
      flowBar.style.width = barW + '%';
    }

    setText('val-spool-rem', data.spool_remaining_g.toFixed(1));
    setText('val-spool-used', data.spool_used_g.toFixed(1));
    const sBar = document.getElementById('spool-bar');
    if (sBar) {
      const initW = (data.spool_used_g + data.spool_remaining_g) || 1000;
      const spoolPct = Math.max(0, Math.min(100, (data.spool_remaining_g / initW) * 100));
      sBar.style.width = spoolPct + '%';
      sBar.style.background = spoolPct > 20 ? 'var(--emerald)' : (spoolPct > 5 ? 'var(--amber)' : 'var(--rose)');
    }

    const switchPill = document.getElementById('switch-pill');
    const runoutBanner = document.getElementById('runout-banner');
    if (data.filament_present) {
      if (switchPill) {
        switchPill.className = 'pill pill-loaded';
        switchPill.textContent = 'FILAMENT PRESENT';
      }
      setText('val-runout-buf', 'LOADED');
      setText('val-runout-mm', '0.0');
      setText('val-runout-status', 'Armed');
      if (runoutBanner) runoutBanner.style.display = 'none';
    } else {
      if (switchPill) {
        switchPill.className = 'pill pill-empty';
        switchPill.textContent = 'RUNOUT / EMPTY';
      }
      if (data.runout_countdown_mm > 0) {
        setText('val-runout-buf', `${data.runout_countdown_mm.toFixed(0)} mm`);
        setText('val-runout-mm', data.runout_countdown_mm.toFixed(1));
        setText('val-runout-status', 'Buffering to Nozzle');
        if (runoutBanner) runoutBanner.style.display = 'flex';
        setText('runout-remain-banner', data.runout_countdown_mm.toFixed(0));
      } else {
        setText('val-runout-buf', 'EXHAUSTED');
        setText('val-runout-mm', '0.0');
        setText('val-runout-status', 'Paused');
      }
    }

    setText('peak-extrude', (data.max_extrude_spd_mm_s || 0).toFixed(1));
    setText('peak-retract', (data.max_retract_spd_mm_s || 0).toFixed(1));
    setText('peak-flow', (data.max_flow_mm3_s || 0).toFixed(1));

    history.push({ spd: data.velocity_mm_s, dia: data.diameter_mm });
    if (history.length > MAX_HISTORY) history.shift();
    drawChart();
  }

  function drawChart() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (history.length < 2) return;

    const w = canvas.width;
    const h = canvas.height;
    const pad = 25;

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let y = pad; y < h - pad; y += 35) {
      ctx.moveTo(pad, y);
      ctx.lineTo(w - pad, y);
    }
    ctx.stroke();

    const step = (w - pad * 2) / (MAX_HISTORY - 1);
    const zeroY = h / 2;

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.beginPath();
    ctx.moveTo(pad, zeroY);
    ctx.lineTo(w - pad, zeroY);
    ctx.stroke();

    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 2;
    ctx.beginPath();
    const startIdx = MAX_HISTORY - history.length;
    history.forEach((pt, i) => {
      const x = pad + (startIdx + i) * step;
      const clamped = Math.max(-50, Math.min(50, pt.spd));
      const y = zeroY - (clamped / 50) * (zeroY - pad);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    history.forEach((pt, i) => {
      const x = pad + (startIdx + i) * step;
      const clampedDia = Math.max(1.50, Math.min(2.00, pt.dia));
      const y = (h - pad) - ((clampedDia - 1.50) / 0.50) * (h - pad * 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  async function tareEmpty() {
    if (confirm("Confirm: Are the sensor bearings completely EMPTY (no filament loaded)?")) {
      const res = await fetch('/tare_empty', {headers: ACTION_HEADERS});
      if (res.ok) {
        alert("Empty bearing reference tared to 0.000 mm & saved to Flash!");
      } else {
        alert("Failed to communicate with sensor.");
      }
    }
  }

  async function calibrateSpan() {
    const val = prompt("Enter reference filament/gauge diameter in mm:", "1.75");
    if (val) {
      const num = parseFloat(val);
      if (!isNaN(num) && num >= 0.5 && num <= 3.5) {
        const res = await fetch('/calibrate_span?target=' + num, {headers: ACTION_HEADERS});
        if (res.ok) {
          alert("Span calibration command sent for " + num.toFixed(3) + " mm!");
        } else {
          alert("Failed to communicate with sensor.");
        }
      } else {
        alert("Invalid diameter value (must be between 0.5 and 3.5 mm).");
      }
    }
  }

  async function resetSpool() {
    if (confirm("Reset spool usage counter back to 0.0 g?")) {
      await fetch('/reset_spool', {headers: ACTION_HEADERS});
    }
  }

  async function resetBowden() {
    if (confirm("Flush saved Bowden tube diameter profile?")) {
      await fetch('/reset_bowden', {headers: ACTION_HEADERS});
    }
  }

  setInterval(poll, 100);
  poll();
</script>
</body>
</html>
"""

class BowdenDelayBuffer:
    """FIFO Queue mapping measured diameter to nozzle arrival after Bowden travel."""
    def __init__(self, bowden_length_mm: float):
        self.bowden_length_mm = max(10.0, bowden_length_mm)
        self.queue = [] # List of tuples: [distance_mm, diameter_mm]
        self.total_extruded_mm = 0.0

    def push(self, delta_mm: float, diameter_mm: float):
        if delta_mm <= 0:
            return
        self.total_extruded_mm += delta_mm
        self.queue.append((self.total_extruded_mm, round(diameter_mm, 4)))

        # Evict elements once subsequent elements have reached or passed the nozzle
        cutoff_dist = self.total_extruded_mm - self.bowden_length_mm
        while len(self.queue) > 1 and self.queue[1][0] <= cutoff_dist:
            self.queue.pop(0)

    def get_current_nozzle_diameter(self, fallback: float = 1.750) -> float:
        """Returns the diameter of the segment entering the nozzle right now."""
        if not self.queue:
            return fallback
        cutoff_dist = self.total_extruded_mm - self.bowden_length_mm
        if cutoff_dist < self.queue[0][0]:
            # The measured segment has not reached the nozzle yet
            return fallback
        # The oldest entry in the queue is currently at the nozzle
        return self.queue[0][1]

    def reset(self):
        """Clears the buffer (e.g. when filament is unloaded or new spool loaded)."""
        self.queue.clear()
        self.total_extruded_mm = 0.0

    def serialize(self) -> dict:
        """Serializes the Bowden tube diameter profile relative to the nozzle."""
        if not self.queue:
            return {"valid": False, "samples": []}

        cutoff_dist = self.total_extruded_mm - self.bowden_length_mm
        # x is distance from nozzle in mm [0 = nozzle, bowden_length_mm = sensor exit]
        # Downsample to ~1mm steps to keep persistence lightweight (<10KB)
        samples = []
        last_x = -999.0
        for dist, dia in self.queue:
            x = round(dist - cutoff_dist, 2)
            if 0.0 <= x <= self.bowden_length_mm and (x - last_x >= 1.0 or dist == self.queue[-1][0]):
                samples.append([x, dia])
                last_x = x

        dias = [dia for _, dia in samples]
        avg_dia = sum(dias) / len(dias) if dias else 1.750
        buffered_len = samples[-1][0] - samples[0][0] if len(samples) > 1 else 0.0

        return {
            "valid": len(samples) > 0,
            "bowden_length_mm": self.bowden_length_mm,
            "buffered_length_mm": round(buffered_len, 2),
            "avg_diameter_mm": round(avg_dia, 4),
            "last_sensor_dia_mm": round(self.queue[-1][1], 4) if self.queue else 1.750,
            "samples_count": len(samples),
            "samples": samples # [[x_mm_from_nozzle, diameter_mm], ...]
        }

    def deserialize(self, data: dict, fallback: float = 1.750) -> bool:
        """Restores the Bowden tube diameter profile from a previous powered-down session."""
        if not data or not data.get("valid", False):
            return False
        samples = data.get("samples", [])
        if not samples:
            return False

        saved_length = data.get("bowden_length_mm", self.bowden_length_mm)
        # Re-anchor coordinate system so total_extruded_mm = self.bowden_length_mm
        # Then cutoff_dist = total_extruded_mm - bowden_length_mm = 0.0
        self.total_extruded_mm = self.bowden_length_mm
        self.queue = []
        for item in samples:
            x_from_nozzle, dia = item[0], item[1]
            if saved_length > 0 and saved_length != self.bowden_length_mm:
                x = x_from_nozzle * (self.bowden_length_mm / saved_length)
            else:
                x = x_from_nozzle
            self.queue.append((round(x, 2), round(dia, 4)))

        return len(self.queue) > 0

    def get_stats(self) -> dict:
        """Returns live statistics about the current Bowden buffer contents."""
        if not self.queue:
            return {"buffered_mm": 0.0, "avg_dia_mm": 1.750, "samples": 0}
        cutoff_dist = self.total_extruded_mm - self.bowden_length_mm
        dias = [dia for dist, dia in self.queue if dist >= cutoff_dist]
        avg_dia = sum(dias) / len(dias) if dias else 1.750
        buf_mm = min(self.bowden_length_mm, self.total_extruded_mm)
        return {
            "buffered_mm": round(buf_mm, 1),
            "avg_dia_mm": round(avg_dia, 3),
            "samples": len(self.queue)
        }


class Indus3DSensorDaemon:
    def __init__(self, config_path: str = CONFIG_FILE_DEFAULT, port_override: str = None,
                 bowden_override: float = None, dry_run: bool = False, monitor: bool = True):
        self.config_path = Path(config_path)
        self.state_path = Path.home() / STATE_FILE_DEFAULT
        self.running = False
        self.serial_conn = None
        self.lock = threading.Lock()
        self.serial_lock = threading.Lock()
        self.dry_run = dry_run
        self.monitor = monitor

        # Load Configuration
        self.load_config()

        if port_override:
            self.configured_port = port_override
        if bowden_override is not None:
            self.bowden_length_mm = max(10.0, bowden_override)

        # Bowden Buffer & Spool Tracker
        self.bowden_buffer = BowdenDelayBuffer(self.bowden_length_mm)
        self.runout_active = False
        self.runout_countdown_mm = 0.0
        self.runout_tolerance_count = 0
        self.has_seen_filament = False

        # Spool & Bowden Metrics Persistence
        self.mass_used_g = 0.0
        self.total_volume_cm3 = 0.0
        self.cached_bowden_data = None
        self.csv_log_path = Path.home() / "indus3d_spool_log.csv"
        self.last_csv_log_pos_mm = 0.0
        self.load_state()

        # Live Telemetry State
        self.telemetry = {
            "connected": False,
            "port": "",
            "position_mm": 0.0,
            "velocity_mm_s": 0.0,
            "motion_direction": "IDLE",
            "volumetric_flow_mm3_s": 0.0,
            "diameter_mm": 0.0,
            "nominal_area_pct": 0.0,
            "filament_present": True,
            "faults": "NORMAL",
            "fault_flags": 0,
            "nozzle_diameter_mm": 1.750,
            "auto_flow_percent": 100.0,
            "runout_countdown_mm": 0.0,
            "spool_used_g": 0.0,
            "spool_remaining_g": self.initial_spool_weight_g,
            "max_extrude_spd_mm_s": 0.0,
            "max_retract_spd_mm_s": 0.0,
            "max_flow_mm3_s": 0.0,
            "bowden_buffered_mm": 0.0,
            "bowden_avg_dia_mm": 1.750,
            "bowden_restored": False,
            "bed_accel_x_mg": 0,
            "bed_accel_y_mg": 0,
            "bed_accel_z_mg": 0,
            "bed_jerk_mg": 0
        }

        # Flow Update Rate Limiter
        self.last_flow_update_pos_mm = 0.0
        self.current_applied_flow_pct = 100.0

        # Clog / Slip Watchdog
        self.slip_active_start_time = None

    def load_config(self):
        if not self.config_path.exists():
            with open(self.config_path, "w") as f:
                f.write(DEFAULT_INI)
            logging.info(f"Created default configuration at {self.config_path}")

        config = configparser.ConfigParser()
        config.read(self.config_path)

        self.configured_port = config.get("sensor", "port", fallback="").strip()
        self.baudrate = config.getint("sensor", "baud", fallback=115200)

        self.bowden_length_mm = config.getfloat("bowden", "bowden_length_mm", fallback=650.0)
        self.runout_margin_mm = config.getfloat("bowden", "runout_margin_mm", fallback=40.0)

        self.material = config.get("spool", "material", fallback="PLA").upper()
        custom_density = config.getfloat("spool", "density_g_cm3", fallback=0.0)
        self.density = custom_density if custom_density > 0 else MATERIAL_DENSITIES.get(self.material, 1.24)
        self.initial_spool_weight_g = config.getfloat("spool", "initial_spool_weight_g", fallback=1000.0)

        self.enable_auto_flow = config.getboolean("features", "enable_auto_flow", fallback=True)
        self.flow_update_interval_mm = config.getfloat("features", "flow_update_interval_mm", fallback=50.0)
        self.min_flow_percent = config.getfloat("features", "min_flow_percent", fallback=85.0)
        self.max_flow_percent = config.getfloat("features", "max_flow_percent", fallback=115.0)

        self.enable_clog_detection = config.getboolean("features", "enable_clog_detection", fallback=True)
        self.slip_threshold_ratio = config.getfloat("features", "slip_threshold_ratio", fallback=0.40)
        self.slip_timeout_seconds = config.getfloat("features", "slip_timeout_seconds", fallback=1.5)

        self.moonraker_url = config.get("moonraker", "url", fallback="http://127.0.0.1:7125").rstrip("/")
        self.moonraker_key = config.get("moonraker", "api_key", fallback="").strip()
        self.api_host = config.get("api", "host", fallback="127.0.0.1").strip() or "127.0.0.1"
        self.api_port = config.getint("api", "port", fallback=7126)

    def load_state(self):
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                    self.mass_used_g = data.get("mass_used_g", 0.0)
                    self.total_volume_cm3 = data.get("total_volume_cm3", 0.0)
                    self.cached_bowden_data = data.get("bowden_buffer", None)
                    b_len = self.cached_bowden_data.get("buffered_length_mm", 0.0) if self.cached_bowden_data else 0.0
                    logging.info(f"Loaded persistent state: {self.mass_used_g:.1f}g used, {b_len:.1f}mm Bowden profile cached")
            except Exception as e:
                logging.warning(f"Could not load state file: {e}")

    def save_state(self):
        try:
            with self.lock:
                bowden_data = self.bowden_buffer.serialize()
                payload = {
                    "material": self.material,
                    "density": self.density,
                    "mass_used_g": self.mass_used_g,
                    "total_volume_cm3": self.total_volume_cm3,
                    "bowden_buffer": bowden_data,
                    "timestamp": time.time()
                }
            with open(self.state_path, "w") as f:
                json.dump(payload, f, indent=2)
            logging.debug("Saved persistent spool and Bowden profile state.")
        except Exception as e:
            logging.error(f"Failed to save state: {e}")

    def log_csv_sample(self, pos_mm: float, dia_mm: float, nozzle_dia_mm: float, speed_mm_s: float, flow_pct: float):
        """Logs continuous spool diameter metrics to a local CSV file (inspired by BDWidth)."""
        try:
            write_header = not self.csv_log_path.exists()
            with open(self.csv_log_path, "a", encoding="utf-8") as f:
                if write_header:
                    f.write("timestamp,position_mm,diameter_mm,nozzle_diameter_mm,speed_mm_s,flow_multiplier_pct\n")
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{pos_mm:.1f},{dia_mm:.3f},{nozzle_dia_mm:.3f},{speed_mm_s:.1f},{flow_pct:.1f}\n")
        except Exception as e:
            logging.debug(f"CSV log error: {e}")

    def find_serial_port(self):
        if self.configured_port and os.path.exists(self.configured_port):
            return self.configured_port

        # Auto-detect Raspberry Pi Pico serial devices (strictly exclude Klipper MCUs and mainboards)
        excluded = set()
        for p in glob.glob("/dev/serial/by-id/*"):
            if "Klipper" in p or any(k in p for k in ("A5069RR4", "usb-0:2.2:1.0", "1a86_USB_Serial")):
                excluded.add(p)
                try:
                    excluded.add(os.path.realpath(p))
                except OSError:
                    pass

        # Exclude any serial port configured in Klipper's printer.cfg
        for cfg in (
            Path("/var/lib/moonraker/config/printer.cfg"),
            Path.home() / "printer_data/config/printer.cfg",
            Path.home() / "klipper_config/printer.cfg",
            Path("/etc/klipper/printer.cfg"),
        ):
            if cfg.is_file():
                try:
                    curr_sec = ""
                    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                        m_sec = re.match(r"^\s*\[([^]]+)\]", line)
                        if m_sec:
                            curr_sec = m_sec.group(1).strip()
                            continue
                        if curr_sec == "mcu" or curr_sec.startswith("mcu "):
                            m_ser = re.match(r"^\s*serial\s*:\s*(\S+)", line)
                            if m_ser:
                                ser_path = m_ser.group(1)
                                excluded.add(ser_path)
                                try:
                                    excluded.add(os.path.realpath(ser_path))
                                except OSError:
                                    pass
                except OSError:
                    pass

        by_id_candidates = [
            p for p in (glob.glob('/dev/serial/by-id/*Raspberry_Pi*') + glob.glob('/dev/serial/by-id/*Pico*'))
            if 'Klipper' not in p and p not in excluded and os.path.realpath(p) not in excluded
        ]
        if by_id_candidates:
            return by_id_candidates[0]

        return None

    def send_klipper_gcode(self, gcode: str):
        """Sends a G-code command to Klipper via Moonraker REST API."""
        if self.dry_run:
            print(f"\n\033[96m>>> [KLIPPER SIMULATED] > {gcode}\033[0m")
            logging.info(f"[KLIPPER SIMULATED] > {gcode}")
            return
        if not self.moonraker_url:
            return
        endpoint = f"{self.moonraker_url}/printer/gcode/script"
        req_data = json.dumps({"script": gcode}).encode("utf-8")
        req = urllib.request.Request(endpoint, data=req_data, headers={"Content-Type": "application/json"})
        if self.moonraker_key:
            req.add_header("X-Api-Key", self.moonraker_key)
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    logging.info(f"[MOONRAKER] Executed G-code: {gcode}")
        except urllib.error.URLError as e:
            # If Moonraker is offline, log prominently during testing so user sees what would have run
            print(f"\n\033[33m>>> [MOONRAKER OFFLINE] Would execute: {gcode}\033[0m")
            logging.debug(f"[MOONRAKER OFFLINE] Call failed ({gcode}): {e}")

    def send_sensor_command(self, cmd_bytes: bytes) -> bool:
        with self.serial_lock:
            if self.serial_conn and self.serial_conn.is_open:
                try:
                    self.serial_conn.write(cmd_bytes)
                    self.serial_conn.flush()
                    time.sleep(0.08)
                    return True
                except Exception as e:
                    logging.error(f"Failed to send sensor command: {e}")
        return False

    def run_serial_loop(self):
        last_save_time = time.time()
        prev_pos_mm = None
        buffer = bytearray()

        while self.running:
            port = self.find_serial_port()
            if not port:
                with self.lock:
                    self.telemetry["connected"] = False
                time.sleep(1.0)
                continue

            try:
                logging.info(f"Connecting to sensor on {port}...")
                ser = serial.Serial(port, self.baudrate, timeout=0.10)
                with self.lock:
                    self.serial_conn = ser
                    self.telemetry["connected"] = True
                    self.telemetry["port"] = port
                ser.reset_input_buffer()
                buffer.clear()
                speed_mm_s = 0.0

                while self.running:
                    # Query binary telemetry (0xF5 0x10) under serial_lock to prevent collision
                    with self.serial_lock:
                        ser.write(bytearray([0xF5, 0x10]))
                        chunk = ser.read(64)
                    if chunk:
                        buffer.extend(chunk)

                    # Look for 33-byte packet: 0x05, 0xFF, 0x10 + 30 bytes payload
                    while len(buffer) >= 33:
                        idx = buffer.find(b'\x05\xff\x10')
                        if idx == -1:
                            buffer = buffer[-2:]
                            break
                        if idx > 0:
                            buffer = buffer[idx:]

                        pkt_len = 41 if len(buffer) >= 41 else 33
                        if len(buffer) < pkt_len:
                            break

                        payload = buffer[3:pkt_len]
                        buffer = buffer[pkt_len:]

                        if pkt_len == 41:
                            (motion_mag, dia_mag, present_byte, fault_flags,
                             motion_turns, motion_ang, total_cnt, total_um,
                             vel_um_s, dia_raw_ang, dia_filt_um, dia_var_um,
                             bed_x_mg, bed_y_mg, bed_z_mg, bed_jerk) = struct.unpack('<BBBBllllhlhhhhhh', payload)
                        else:
                            (motion_mag, dia_mag, present_byte, fault_flags,
                             motion_turns, motion_ang, total_cnt, total_um,
                             vel_um_s, dia_raw_ang, dia_filt_um, dia_var_um) = struct.unpack('<BBBBllllhlhh', payload)
                            bed_x_mg, bed_y_mg, bed_z_mg, bed_jerk = 0, 0, 0, 0

                        pos_mm = total_um / 1000.0
                        speed_mm_s = vel_um_s / 1000.0
                        dia_mm = dia_filt_um / 1000.0
                        present = bool(present_byte)

                        # Restore Bowden buffer from persistent storage on first boot packet
                        if self.cached_bowden_data is not None:
                            cached = self.cached_bowden_data
                            self.cached_bowden_data = None
                            if present:
                                if self.bowden_buffer.deserialize(cached):
                                    stats = self.bowden_buffer.get_stats()
                                    logging.info(f"[BOWDEN PERSISTENCE] Restored pre-measured filament in tube: {stats['buffered_mm']:.1f}mm (Avg Dia: {stats['avg_dia_mm']:.3f}mm).")
                                    with self.lock:
                                        self.telemetry["bowden_restored"] = True
                                        self.telemetry["bowden_buffered_mm"] = stats["buffered_mm"]
                                        self.telemetry["bowden_avg_dia_mm"] = stats["avg_dia_mm"]
                                    self.send_klipper_gcode(f'RESPOND TYPE=echo MSG="Indus3D: Restored {stats["buffered_mm"]:.0f}mm pre-measured filament in Bowden tube (Avg: {stats["avg_dia_mm"]:.3f}mm)"')
                            else:
                                logging.info("[BOWDEN PERSISTENCE] Sensor is empty on startup. Clearing saved Bowden tube profile.")
                                self.bowden_buffer.reset()
                                self.save_state()

                        # Linear delta since last sample
                        if prev_pos_mm is None:
                            delta_mm = 0.0
                        else:
                            delta_mm = max(0.0, pos_mm - prev_pos_mm)
                        prev_pos_mm = pos_mm

                        # 1. Update Bowden Delay Queue
                        if delta_mm > 0 and dia_mm > 0.5:
                            self.bowden_buffer.push(delta_mm, dia_mm)

                            # Integrate Volume & Mass
                            area_mm2 = math.pi * ((dia_mm / 2.0) ** 2)
                            vol_cm3 = (delta_mm * area_mm2) / 1000.0
                            self.total_volume_cm3 += vol_cm3
                            self.mass_used_g += vol_cm3 * self.density

                            # BDWidth-style continuous spool profile CSV logging (every 5 mm)
                            if abs(pos_mm - self.last_csv_log_pos_mm) >= 5.0:
                                self.last_csv_log_pos_mm = pos_mm
                                self.log_csv_sample(pos_mm, dia_mm, nozzle_dia_mm, speed_mm_s, self.current_applied_flow_pct)

                        # 2. Compute Delayed Nozzle Diameter & Auto-Flow Multiplier
                        nozzle_dia_mm = self.bowden_buffer.get_current_nozzle_diameter(fallback=1.750)
                        if self.enable_auto_flow and nozzle_dia_mm > 0.5:
                            nom_area = math.pi * ((1.750 / 2.0) ** 2)
                            act_area = math.pi * ((nozzle_dia_mm / 2.0) ** 2)
                            raw_flow_pct = (nom_area / act_area) * 100.0
                            target_flow_pct = max(self.min_flow_percent, min(self.max_flow_percent, raw_flow_pct))

                            # Apply to Klipper if extruded enough distance and difference > 0.5%
                            if (pos_mm - self.last_flow_update_pos_mm >= self.flow_update_interval_mm and
                                    abs(target_flow_pct - self.current_applied_flow_pct) >= 0.5):
                                self.current_applied_flow_pct = target_flow_pct
                                self.last_flow_update_pos_mm = pos_mm
                                self.send_klipper_gcode(f"M221 S{target_flow_pct:.1f}")

                        # 3. Smart Runout Countdown Logic (Debounced with tolerance count)
                        if not present:
                            self.runout_tolerance_count += 1
                            if self.runout_tolerance_count >= 5: # Require 5 consecutive packets (~200ms)
                                if self.has_seen_filament:
                                    if not self.runout_active:
                                        self.runout_active = True
                                        self.runout_countdown_mm = max(10.0, self.bowden_length_mm - self.runout_margin_mm)
                                        logging.warning(f"[RUNOUT] Filament left sensor! Countdown started: {self.runout_countdown_mm:.1f} mm")
                                        self.send_klipper_gcode(f'RESPOND TYPE=echo MSG="Filament Sensor: Runout detected. Printing remaining {self.runout_countdown_mm:.0f}mm buffer..."')
                                    else:
                                        if delta_mm > 0:
                                            self.runout_countdown_mm -= delta_mm
                                            if self.runout_countdown_mm <= 0:
                                                self.runout_countdown_mm = 0.0
                                                logging.critical("[RUNOUT] Buffer exhausted! Triggering SMART_RUNOUT_PAUSE.")
                                                self.send_klipper_gcode("SMART_RUNOUT_PAUSE")
                        else:
                            self.runout_tolerance_count = 0
                            self.has_seen_filament = True
                            if self.runout_active:
                                logging.info("[RUNOUT] New filament detected! Resetting runout state.")
                                self.runout_active = False
                                self.runout_countdown_mm = 0.0

                        # 4. Volumetric Flow Calculation
                        if dia_mm > 0.5:
                            act_area = math.pi * ((dia_mm / 2.0) ** 2)
                            nom_area = math.pi * ((1.750 / 2.0) ** 2)
                            area_pct = (act_area / nom_area) * 100.0
                            flow_mm3_s = speed_mm_s * act_area
                        else:
                            area_pct = 0.0
                            flow_mm3_s = 0.0

                        # Direction String
                        if speed_mm_s > 0.4:
                            dir_str = "EXTRUDE"
                        elif speed_mm_s < -0.4:
                            dir_str = "RETRACT"
                        else:
                            dir_str = "IDLE"

                        # Update Shared Telemetry State
                        with self.lock:
                            self.telemetry["position_mm"] = pos_mm
                            self.telemetry["velocity_mm_s"] = speed_mm_s
                            self.telemetry["motion_direction"] = dir_str
                            self.telemetry["volumetric_flow_mm3_s"] = flow_mm3_s
                            self.telemetry["raw_dia_angle"] = dia_raw_ang
                            self.telemetry["raw_motion_angle"] = motion_ang
                            self.telemetry["diameter_mm"] = dia_mm
                            self.telemetry["nominal_area_pct"] = area_pct
                            self.telemetry["filament_present"] = present
                            self.telemetry["fault_flags"] = fault_flags
                            self.telemetry["nozzle_diameter_mm"] = nozzle_dia_mm
                            self.telemetry["auto_flow_percent"] = self.current_applied_flow_pct
                            self.telemetry["runout_countdown_mm"] = self.runout_countdown_mm
                            self.telemetry["spool_used_g"] = self.mass_used_g
                            self.telemetry["spool_remaining_g"] = max(0.0, self.initial_spool_weight_g - self.mass_used_g)

                            b_stats = self.bowden_buffer.get_stats()
                            self.telemetry["bowden_buffered_mm"] = b_stats["buffered_mm"]
                            self.telemetry["bowden_avg_dia_mm"] = b_stats["avg_dia_mm"]
                            self.telemetry["bed_accel_x_mg"] = bed_x_mg
                            self.telemetry["bed_accel_y_mg"] = bed_y_mg
                            self.telemetry["bed_accel_z_mg"] = bed_z_mg
                            self.telemetry["bed_jerk_mg"] = bed_jerk

                            if speed_mm_s > self.telemetry["max_extrude_spd_mm_s"]:
                                self.telemetry["max_extrude_spd_mm_s"] = speed_mm_s
                                self.telemetry["max_flow_mm3_s"] = flow_mm3_s
                            elif speed_mm_s < self.telemetry["max_retract_spd_mm_s"]:
                                self.telemetry["max_retract_spd_mm_s"] = speed_mm_s

                    # Save persistent spool & Bowden state every 20 seconds during printing, or 60s when idle
                    save_interval = 20.0 if abs(speed_mm_s) > 0.1 else 60.0
                    if time.time() - last_save_time >= save_interval:
                        last_save_time = time.time()
                        self.save_state()

                    time.sleep(0.04) # 25 Hz host query loop

            except Exception as e:
                logging.error(f"Serial communication error: {e}")
                with self.lock:
                    self.telemetry["connected"] = False
                time.sleep(2.0)
            finally:
                with self.lock:
                    self.serial_conn = None
                if 'ser' in locals() and ser.is_open:
                    ser.close()

    def start_http_server(self):
        daemon_self = self

        class StatusHandler(BaseHTTPRequestHandler):
            ACTION_PATHS = ("/tare_empty", "/calibrate_span", "/reset_spool", "/reset_bowden")

            def do_GET(self):
                clean_path = self.path.split('?')[0]
                # These GETs change state. A custom header cannot be sent by a web page on
                # another origin without a CORS preflight (which this server never grants),
                # so requiring it blocks drive-by requests from a browser on this machine.
                if clean_path in self.ACTION_PATHS and self.headers.get("X-Indus3D-Action") != "1":
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error": "X-Indus3D-Action: 1 header required for control endpoints"}')
                    return
                if clean_path in ["/status", "/api/status"]:
                    with daemon_self.lock:
                        data = dict(daemon_self.telemetry)
                    payload = json.dumps(data, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.end_headers()
                    self.wfile.write(payload)
                elif clean_path in ["/", "/dashboard", "/index.html", "/index"] or clean_path.startswith("/dashboard"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
                elif clean_path == "/tare_empty":
                    ok = daemon_self.send_sensor_command(bytearray([0xF5, 0x22]))
                    self.send_response(200 if ok else 500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "ok", "message": "Empty bearing reference tared to 0.000 mm & saved to Flash"}')
                elif clean_path == "/calibrate_span":
                    target_mm = 1.75
                    try:
                        from urllib.parse import urlparse, parse_qs
                        qs = parse_qs(urlparse(self.path).query)
                        if "target" in qs:
                            target_mm = float(qs["target"][0])
                    except Exception:
                        pass
                    cal_um = int(round(target_mm * 1000.0))
                    low = cal_um & 0xFF
                    high = (cal_um >> 8) & 0xFF
                    ok = daemon_self.send_sensor_command(bytearray([0xF5, 0x23, low, high]))
                    self.send_response(200 if ok else 500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "target_mm": target_mm}).encode("utf-8"))
                elif clean_path == "/reset_spool":
                    daemon_self.mass_used_g = 0.0
                    daemon_self.total_volume_cm3 = 0.0
                    daemon_self.save_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "ok", "message": "Spool usage reset to 0g"}')
                elif clean_path == "/download_csv":
                    if daemon_self.csv_log_path.exists():
                        with open(daemon_self.csv_log_path, "rb") as f:
                            csv_bytes = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/csv")
                        self.send_header("Content-Disposition", 'attachment; filename="indus3d_spool_log.csv"')
                        self.end_headers()
                        self.wfile.write(csv_bytes)
                    else:
                        self.send_response(404)
                        self.end_headers()
                elif clean_path == "/reset_bowden":
                    with daemon_self.lock:
                        daemon_self.bowden_buffer.reset()
                        daemon_self.telemetry["bowden_restored"] = False
                        daemon_self.telemetry["bowden_buffered_mm"] = 0.0
                    daemon_self.save_state()
                    daemon_self.send_klipper_gcode('RESPOND TYPE=echo MSG="Indus3D: Bowden tube diameter buffer reset to 0mm"')
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "ok", "message": "Bowden tube buffer reset to 0mm"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass # Suppress HTTP access logging in console

        server = HTTPServer((self.api_host, self.api_port), StatusHandler)
        self.http_server = server
        logging.info(f"Indus3D REST API listening on http://{self.api_host}:{self.api_port}/status")
        server.serve_forever()

    def monitor_loop(self):
        """Live updating terminal status monitor for diagnostics & dry testing."""
        import shutil
        while self.running:
            time.sleep(0.08)
            with self.lock:
                if not self.telemetry["connected"]:
                    continue
                pos = self.telemetry["position_mm"]
                spd = self.telemetry["velocity_mm_s"]
                flow_vol = self.telemetry["volumetric_flow_mm3_s"]
                dia = self.telemetry["diameter_mm"]
                nozzle_dia = self.telemetry["nozzle_diameter_mm"]
                flow = self.telemetry["auto_flow_percent"]
                spool = self.telemetry["spool_remaining_g"]
                pres = self.telemetry["filament_present"]
                ro = self.telemetry["runout_countdown_mm"]

            pres_str = "\033[92mFILAMENT OK\033[0m" if pres else "\033[91mEMPTY\033[0m"
            ro_str = f" | \033[93mRUNOUT REMAIN: {ro:.0f}mm\033[0m" if ro > 0 else ""
            line = (f"\r[STATUS] Pos: {pos:7.1f}mm | Spd: {spd:+5.1f}mm/s ({flow_vol:4.1f}mm³/s) | "
                    f"Dia: {dia:.3f}mm (Nozzle: {nozzle_dia:.3f}mm) | Flow: {flow:5.1f}% | "
                    f"Spool: {spool:.1f}g | [{pres_str}]{ro_str}")
            cols = shutil.get_terminal_size((120, 20)).columns
            if len(line) > cols - 1:
                line = line[:cols - 4] + "..."
            print(line.ljust(cols - 1), end="", flush=True)

    def start(self):
        self.running = True
        logging.info("Starting Indus3D Filament Sensor Daemon...")

        # Graceful shutdown handler to guarantee state save on systemd stop or ctrl-c
        def handle_signal(sig, frame):
            logging.info(f"Received signal {sig}, terminating gracefully...")
            self.running = False
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # Start HTTP server thread
        http_thread = threading.Thread(target=self.start_http_server, daemon=True)
        http_thread.start()

        # Start Terminal Status Monitor if enabled
        if self.monitor:
            mon_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            mon_thread.start()

        # Start Serial Reader Loop
        try:
            self.run_serial_loop()
        except KeyboardInterrupt:
            logging.info("Shutting down daemon...")
        finally:
            self.running = False
            self.save_state()
            if self.monitor:
                print("\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Indus3D Smart Filament Sensor Host Daemon")
    parser.add_argument("--port", "-p", default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--bowden", "-b", type=float, default=None, help="Override Bowden tube length in mm (e.g. 50.0 for desk test)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Simulate Moonraker/Klipper calls without network connection")
    parser.add_argument("--no-monitor", dest="monitor", action="store_false", default=True, help="Disable terminal status monitor")
    parser.add_argument("--config", "-c", default=CONFIG_FILE_DEFAULT, help="Path to configuration INI file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    daemon = Indus3DSensorDaemon(
        config_path=args.config,
        port_override=args.port,
        bowden_override=args.bowden,
        dry_run=args.dry_run,
        monitor=args.monitor
    )
    daemon.start()


if __name__ == "__main__":
    main()
