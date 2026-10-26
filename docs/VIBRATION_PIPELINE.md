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

## Self-Calibrating Baseline

Instead of hardcoded thresholds, the system uses a dedicated **calibration print** (hollow octagon printed at multiple speeds and Z-heights). This establishes a per-printer baseline so the anomaly detection engine can dynamically recognize deviations from the known "healthy" baseline of that specific machine.

## Hardware Status

*Dependency Check:* This pipeline depends on the accelerometer hardware being physically wired. The Rust binary is compiled and tested. A dual-MCU setup (RP2040/Pico bridging a bed-mounted ADXL345) is the reference hardware. Hardware readiness must be confirmed before the live UDP ingestion path activates.
