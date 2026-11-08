# Indus3D Lab — offline model checks

These tools turn a read-only Indus3D Lab telemetry capture into calculations
that can be checked against a real print. They only read files and write a
report; they do not open a network connection, send G-code, or control a
printer.

## `derive_physics_report.py`

```bash
python3 derive_physics_report.py ../runs/part-001.jsonl \
  --gcode /path/to/part.gcode \
  --toolhead-mass-kg 0.40 \
  --output-dir ../reports/part-001-physics
```

The report contains the following independently inspectable calculations:

- **Motion:** reported 3D path, velocity, acceleration and a conservative
  translational kinetic-energy estimate: `E = ½mv²`.  These describe the
  telemetry stream, not a replacement for Klipper's safety limits.
- **Thermal and energy:** min/mean/max heater temperatures, temperature slope
  `(T₂ - T₁) / Δt`, plus trapezoidal integration of available PZEM power data:
  `E_Wh = Σ((Pᵢ + Pᵢ₊₁)/2 × Δt / 3600)`.  Missing power samples are reported
  instead of being treated as zero.
- **Vibration:** RMS/magnitude, resonance peak frequency and kurtosis summaries
  for each reported axis.  It uses the values already calculated by the
  Indus3D Rust/Python DSP pipeline; it does not invent sensor readings.
- **G-code estimate:** a transparent lower-bound motion time obtained by adding
  `distance / (F / 60)` for linear `G0`/`G1` moves. It deliberately excludes
  acceleration, dwell, heating, firmware look-ahead and extrusion pressure,
  so it must be compared with actual elapsed time rather than used as an ETA.

The JSON report includes formula names, assumptions, and raw sample counts so
it can be reviewed or plotted elsewhere.
