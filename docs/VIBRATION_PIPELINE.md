# Real-Time Vibration & Structural Dynamics Pipeline

*This document covers the implemented Rust DSP pipeline and its integration with the Python quality controller, including the acoustic/structural models derived from the research literature.*

## Overview

The system continuously samples an ADXL345 / LIS2DW accelerometer (attached to the toolhead and/or bed) at **3200 Hz** during a live print.

This data feeds a real-time Digital Signal Processing (DSP) pipeline that computes:
- **FFT (Fast Fourier Transform):** Isolates and visualises the frequency content of the printer's movements.
- **PSD (Power Spectral Density):** Maps how vibration energy is distributed across those frequencies.
- **Kurtosis:** A statistical measure of signal "spikiness" to catch sudden mechanical anomalies (layer shifts, failing bearings, nozzle impacts) rather than just steady-state resonance.
- **RMS:** Root-mean-square amplitude for per-axis stress scoring.
- **Estimated stiffness and mass:** Structural parameter extraction from frequency response.
- **Torque ripple:** Stepper electromagnetic noise fingerprint.

## Implemented Architecture

### Rust DSP Engine (`backend/dsp/`)

The DSP pipeline runs as a fully standalone Rust process with no Python GIL dependency.

**Communication protocol:**
- **Input:** UDP socket `127.0.0.1:3200` — receives raw ADXL CSV lines: `t,x,y,z\n` at 3200 Hz
- **Output:** UDP socket `127.0.0.1:3201` — emits 1 Hz aggregated JSON telemetry back to Python

**Per-window computation (1-second sliding window, 50% overlap):**
```
Window → FFT (RustFFT) → PSD → peak_hz, max_magnitude, kurtosis, rms,
                                estimated_stiffness, estimated_mass, torque_ripple
```

Each axis (X, Y, Z) has an independent `DspProcessor` instance.

**Output JSON schema** (sent to Python every ~1 second):
```json
{
  "x": { "hz": 42.3, "mag": 0.18, "kurtosis": 2.1, "rms": 0.04, "stiffness": 850.0, "mass": 210.0, "torque_ripple": 0.003 },
  "y": { ... },
  "z": { ... }
}
```

### Python DSP Bridge (`backend/workers/dsp_bridge.py`)

Listens on `127.0.0.1:3201` and forwards aggregated vibration data to the main telemetry event loop. Applies `SO_REUSEADDR` for clean restart behaviour.

### Mass-Adaptive Input Shaping (TVIST model)

The quality controller's `_shaper_control()` now uses **`calc_mass_adaptive_shaper_frequency()`** (Paper 2.1.64 — Ebbesen et al., 2019) instead of the previous simple mass-ratio formula.

**Mathematical model:**

$$\zeta(t) = \min\!\left(0.30,\; \zeta_0 \cdot \left(1 + k_\zeta \frac{m_\text{part}}{m_\text{bed}}\right)\right)$$

$$f_n(t) = \frac{f_0}{\sqrt{1 - \zeta_0^2}} \cdot \sqrt{\frac{m_\text{bed}}{m_\text{bed} + m_\text{part}(t)}}$$

$$f_d(t) = f_n(t) \cdot \sqrt{1 - \zeta(t)^2}$$

$$\Delta_2 = \frac{0.5}{f_d(t)} \quad \text{(ZV shaper second impulse delay)}$$

where $\zeta_0 = 0.08$ is the baseline structural damping ratio, $k_\zeta = 0.02$ is the viscoelastic growth factor, and $m_\text{part}(t)$ is the accumulated filament mass computed from flow integral.

This improves on the legacy formula by accounting for **viscoelastic damping growth** as the part builds up — heavy prints on a bed slinger are damped differently than light ones.

**New metric exposed:** `active["zeta"]` — live structural damping ratio.

### Fast Kurtogram — Acoustic Flow Stability (Paper 2.1.31)

Kurtosis is particularly sensitive to **non-Gaussian impulsive events** in the acceleration signal. In the context of FFF printing:

| Kurtosis Range | Physical Interpretation |
|---|---|
| K < 3.0 | Gaussian (healthy, steady-state motion) |
| 3.0–5.0 | Minor irregularities (vibration boundary) |
| 5.0–8.0 | **Intermittent stick-slip or layer shift risk** |
| > 8.0 | **Active anomaly — bearing failure, clog, or nozzle impact** |

The `kurtosis` field in the DSP output is consumed by the Python backend as a component of the per-axis `stress_score`. Axis-wise stress scores drive:
- **SCV (Square Corner Velocity)** adjustments via `calc_dynamic_jerk()`
- **Acceleration** limits via `calc_dynamic_accel()`
- **Z-axis warpage** detection (Z-stress → F_z proxy, see below)

### Warpage Detection via Z-Axis Stress (Paper 2.1.28)

The Z-axis DSP stress score serves as a hardware-free **warpage force proxy**:

$$F_{z,\text{est}} = S_Z \cdot F_{\text{max}} \quad (F_{\text{max}} = 20 \text{ N})$$

$$\frac{1}{k_\text{eq}} = \frac{1}{k_m} + \frac{1}{k_p} \quad\Rightarrow\quad \Delta h_\text{warp} = \frac{F_z}{k_\text{eq}} + h_\text{layer}$$

where $S_Z \in [0,1]$ is the normalised Z-axis stress, $k_m = 50\,\text{N/mm}$ is machine stiffness, and $k_p = 15\,\text{N/mm}$ is estimated part stiffness.

When $\Delta h_\text{warp} > 0.35\,\text{mm}$, the quality controller issues a babystep Z-hop:
```gcode
G91
G1 Z0.3 F600
G90
```

### Auto Z-Offset & First Layer Bed Adhesion Optimization (Tribo-Acoustic Squeeze-Flow & Contact Mechanics)

First-layer adhesion failure stems from microscopic deviations between the nozzle orifice and the textured build surface:
- **Nozzle too high ($h > h^*$):** Inadequate ribbon squeeze, insufficient contact width $w < w^*$, lower interfacial thermal conduction, leading to thermal contraction detachment.
- **Nozzle too low ($h < h^*$):** Viscous polymer melt backpressure spikes, nozzle scrapes against PEI asperities, extruder stepper motor skips steps.

The Indus3D digital twin couples the **toolhead accelerometer** (`LIS2DW` on BigTreeTech `EBB36`) with the **Rust DSP engine** (`backend/dsp/`) to solve this across two distinct operational regimes:

#### 1. Pre-Print Touch-Down Probing (Hertzian Dynamic Contact)
The toolhead descends in Z at low velocity ($v_z \approx 1 - 2\text{ mm/s}$). Before contact ($z > z_\text{bed}$), contact force $F_\text{contact} = 0$. At contact ($z \le z_\text{bed}$), Hertzian contact stiffness increases discontinuously:

$$F_\text{contact}(\delta) = \frac{4}{3} E^* \sqrt{R} \, \delta^{3/2}, \quad K_\text{contact} = \frac{dF}{d\delta} = 2 E^* \sqrt{R \delta}$$

$$\frac{1}{E^*} = \frac{1 - \nu_\text{nozzle}^2}{E_\text{nozzle}} + \frac{1 - \nu_\text{bed}^2}{E_\text{bed}}$$

This produces an instantaneous time-domain jerk spike ($j_z = d\ddot{z}/dt$) and a statistical kurtosis surge ($\gamma_2 > 6.0$):
- **Contact Trigger Threshold:** $|j_z| > 400.0\text{ g/s}$ OR $\gamma_2 > 6.0$.
- Allows establishing true physical $Z=0$ directly at the nozzle tip, bypassing probe thermal drift.

#### 2. In-Situ First-Layer Hydrodynamics & Asperity Friction (HFFI Metric)
During first-layer extrusion, polymer melt squeeze-flow follows the Stefan lubrication power-law equation:

$$P(r) \approx K \left(\frac{2n + 1}{n}\right)^n \left(\frac{\dot{V}}{\pi r h^{2n+1}}\right)^n \implies F_\text{lift}(h) \propto \frac{\eta \, v_z \, R_\text{land}^4}{h^3}$$

When the gap approaches the bed roughness ($h \le R_a \approx 15 - 25\,\mu\text{m}$), Coulomb-Stribeck asperity collisions between the nozzle land and PEI grains excite high-frequency acoustic emission:

$$f_\text{asperity} \approx \frac{v_\text{toolhead}}{\lambda_\text{texture}} \approx \frac{50\text{ mm/s}}{40\,\mu\text{m}} \approx 1250\text{ Hz}$$

The Rust DSP engine computes the **High-Frequency Friction Index (HFFI)**:

$$\text{HFFI} = \frac{\int_{1200\text{ Hz}}^{1600\text{ Hz}} S_{aa}(f) \, df}{\int_{20\text{ Hz}}^{400\text{ Hz}} S_{aa}(f) \, df}$$

| HFFI Range | Print Regime | Diagnosis | Closed-Loop Action |
|:---|:---|:---|:---|
| $\text{HFFI} > 0.38$ | **Rubbing** | Nozzle dragging against PEI asperities | Autonomous injection: `SET_GCODE_OFFSET Z_ADJUST=+0.025 MOVE=1` |
| $0.05 \le \text{HFFI} \le 0.38$ | **Optimal Squish** | Viscous melt ribbon damping, optimal contact area | Maintain current Z; optimal adhesion achieved |
| $\text{HFFI} < 0.05$ | **Under-Squish** | Nozzle floating above bed, weak polymer spread | Autonomous injection: `SET_GCODE_OFFSET Z_ADJUST=-0.015 MOVE=1` |

#### 3. Closed-Loop Safety & Execution
- **Active Window:** Only runs during Layer 1 ($Z \le 0.35\text{ mm}$).
- **Rate-Limiting Cooldown:** Minimum 2.0 seconds between adjustments to permit acoustic settling.
- **Cumulative Bounds:** Clamped strictly within $[-0.08\text{ mm}, +0.08\text{ mm}]$ and verified through `bed_safety.clamp_z_offset()` to eliminate any possibility of bed collision.

## Self-Calibrating Baseline

Instead of hardcoded thresholds, the system uses a dedicated **calibration print** (hollow octagon printed at multiple speeds and Z-heights). This establishes a per-printer baseline so the anomaly detection engine can dynamically recognize deviations from the known "healthy" baseline of that specific machine.

## Hardware Status

- **Toolhead Accelerometer:** BigTreeTech EBB36 Gen2 onboard `LIS2DW` connected via high-speed SPI (`EBB:PB1`).
- **Eddy-Current Surface Profiler:** BigTreeTech Eddy USB (`ldc1612` inductive coil probe) for high-density rapid bed mesh mapping.
- **Rust DSP Subprocess:** `indus3d-dsp` running in release mode (`UDP 3200` ingestion, `UDP 3201` telemetry broadcast, `UDP 3202` collision alerts).
