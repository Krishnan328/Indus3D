// dsp/src/dsp.rs — Core DSP processor
//
// Two processing paths:
//
//   FAST PATH  — called per-batch (~32 samples, < 15 ms latency)
//                Detects instantaneous g-force spikes and kurtosis impulses.
//                Returns an Option<CollisionEvent> that main.rs immediately
//                broadcasts on port 3202 so Python can pause the printer.
//
//   SLOW PATH  — called once per filled 1-second Welch window (1 Hz output)
//                Hanning + FFT + motor-step notch filter + structural metrics.
//                Returns a DspResult sent to Python on port 3201.

use rustfft::{num_complex::Complex, FftPlanner};

// ── Collision thresholds (tunable at build time via env vars if needed) ──────
/// g-force magnitude √(x²+y²+z²) above which we call it a collision
pub const COLLISION_G_THRESHOLD:  f32 = 4.5;
/// kurtosis spike above which we flag an impulse even without a g spike
pub const KURTOSIS_IMPULSE_LIMIT: f32 = 15.0;
/// Minimum inter-event gap in seconds to suppress repeated alerts
pub const COLLISION_DEBOUNCE_S:   f32 = 0.5;

// ── Motor-step notch filter bandwidth (Hz each side of the step frequency) ──
const NOTCH_HALF_BW: f32 = 3.0;

// ─────────────────────────────────────────────────────────────────────────────
// Public types
// ─────────────────────────────────────────────────────────────────────────────

/// Emitted by the fast-path detector when a physical impact is detected.
#[derive(Debug, Clone, serde::Serialize)]
pub struct CollisionEvent {
    /// Peak vector magnitude at the moment of detection (g)
    pub peak_g: f32,
    /// Kurtosis of the triggering batch
    pub kurtosis: f32,
    /// Axis that crossed the threshold first ("x","y","z","xyz")
    pub axis: String,
    /// UNIX timestamp of detection
    pub timestamp: f64,
    /// Human-readable reason
    pub reason: String,
}

/// Spectral analysis result produced once per 1-second sliding window.
#[derive(Debug, serde::Serialize)]
pub struct DspResult {
    pub peak_hz:            f32,
    pub max_magnitude:      f32,
    pub kurtosis:           f32,
    pub rms:                f32,
    pub estimated_stiffness: f32,
    pub estimated_mass:     f32,
    pub torque_ripple:      f32,
    /// The frequency bin that was notched out (motor step excitation), or 0
    pub notched_hz:         f32,
}

// ─────────────────────────────────────────────────────────────────────────────
// FastPathDetector — per-batch impact & impulse checker
// ─────────────────────────────────────────────────────────────────────────────

pub struct FastPathDetector {
    /// Circular history for per-axis recent max-g tracking
    history_x: Vec<f32>,
    history_y: Vec<f32>,
    history_z: Vec<f32>,
    capacity:  usize,
    /// Wall-clock timestamp of last emitted collision event
    last_event_time: std::time::Instant,
}

impl FastPathDetector {
    pub fn new(history_len: usize) -> Self {
        Self {
            history_x: Vec::with_capacity(history_len),
            history_y: Vec::with_capacity(history_len),
            history_z: Vec::with_capacity(history_len),
            capacity:  history_len,
            last_event_time: std::time::Instant::now()
                - std::time::Duration::from_secs(10),
        }
    }

    /// Feed a small batch of raw samples (any length).
    /// Returns Some(CollisionEvent) if a crash-level event is detected.
    pub fn feed(&mut self, xs: &[f32], ys: &[f32], zs: &[f32]) -> Option<CollisionEvent> {
        // Debounce — don't re-trigger within COLLISION_DEBOUNCE_S
        let elapsed = self.last_event_time.elapsed().as_secs_f32();
        let debounced = elapsed < COLLISION_DEBOUNCE_S;

        let n = xs.len().min(ys.len()).min(zs.len());
        if n == 0 {
            return None;
        }

        // Compute per-sample vector magnitude and track kurtosis of the batch
        let mut max_g     = 0.0f32;
        let mut peak_axis = "xyz";
        let mut sum_g     = 0.0f32;
        let mut sum_g2    = 0.0f32;
        let mut max_abs_x = 0.0f32;
        let mut max_abs_y = 0.0f32;
        let mut max_abs_z = 0.0f32;

        for i in 0..n {
            let g = (xs[i] * xs[i] + ys[i] * ys[i] + zs[i] * zs[i]).sqrt();
            sum_g  += g;
            sum_g2 += g * g;
            if xs[i].abs() > max_abs_x { max_abs_x = xs[i].abs(); }
            if ys[i].abs() > max_abs_y { max_abs_y = ys[i].abs(); }
            if zs[i].abs() > max_abs_z { max_abs_z = zs[i].abs(); }
            if g > max_g {
                max_g = g;
                peak_axis = if xs[i].abs() >= ys[i].abs() && xs[i].abs() >= zs[i].abs() {
                    "x"
                } else if ys[i].abs() >= zs[i].abs() {
                    "y"
                } else {
                    "z"
                };
            }
        }

        // Kurtosis of vector magnitudes
        let mean = sum_g / n as f32;
        let variance = (sum_g2 / n as f32) - (mean * mean);
        let mut m4 = 0.0f32;
        for i in 0..n {
            let g = (xs[i] * xs[i] + ys[i] * ys[i] + zs[i] * zs[i]).sqrt();
            let d = g - mean;
            m4 += d * d * d * d;
        }
        m4 /= n as f32;
        let kurtosis = if variance > 1e-6 { m4 / (variance * variance) } else { 0.0 };

        // Update rolling history for trend tracking
        self.push_history(max_abs_x, max_abs_y, max_abs_z);

        if debounced {
            return None;
        }

        // ── Detection logic ────────────────────────────────────────────────
        let g_triggered       = max_g > COLLISION_G_THRESHOLD;
        let kurtosis_triggered = kurtosis > KURTOSIS_IMPULSE_LIMIT && max_g > 1.5;

        if g_triggered || kurtosis_triggered {
            self.last_event_time = std::time::Instant::now();
            let reason = if g_triggered {
                format!("Impact: peak g-force {:.2}g on {}-axis (threshold {:.1}g)",
                        max_g, peak_axis, COLLISION_G_THRESHOLD)
            } else {
                format!("Impulse: kurtosis {:.1} on {}-axis (threshold {:.1})",
                        kurtosis, peak_axis, KURTOSIS_IMPULSE_LIMIT)
            };
            return Some(CollisionEvent {
                peak_g:    max_g,
                kurtosis,
                axis:      peak_axis.to_string(),
                timestamp: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64(),
                reason,
            });
        }

        None
    }

    fn push_history(&mut self, x: f32, y: f32, z: f32) {
        if self.history_x.len() >= self.capacity {
            self.history_x.remove(0);
            self.history_y.remove(0);
            self.history_z.remove(0);
        }
        self.history_x.push(x);
        self.history_y.push(y);
        self.history_z.push(z);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SlowPathProcessor — 1-Hz Hanning + FFT + notch filter
// ─────────────────────────────────────────────────────────────────────────────

pub struct SlowPathProcessor {
    planner:     FftPlanner<f32>,
    window_size: usize,
    sample_rate: f32,
}

impl SlowPathProcessor {
    pub fn new(window_size: usize, sample_rate: f32) -> Self {
        Self {
            planner: FftPlanner::new(),
            window_size,
            sample_rate,
        }
    }

    /// Run Hanning-windowed FFT on a 1-second sample window.
    /// `step_freq_hz` — the fundamental motor step excitation frequency at the
    /// current carriage velocity. Pass 0.0 if unknown (skips notch filter).
    pub fn process_window(&mut self, data: &[f32], step_freq_hz: f32) -> DspResult {
        let n = data.len();
        if n == 0 {
            return DspResult {
                peak_hz: 0.0, max_magnitude: 0.0, kurtosis: 0.0, rms: 0.0,
                estimated_stiffness: 0.0, estimated_mass: 0.0,
                torque_ripple: 0.0, notched_hz: 0.0,
            };
        }

        // 1. RMS and kurtosis on raw signal
        let mut sum = 0.0f32;
        let mut sum_sq = 0.0f32;
        for &v in data { sum += v; sum_sq += v * v; }
        let mean     = sum / n as f32;
        let variance = (sum_sq / n as f32) - (mean * mean);
        let rms      = variance.max(0.0).sqrt();

        let mut m4 = 0.0f32;
        for &v in data {
            let d = v - mean;
            let d2 = d * d;
            m4 += d2 * d2;
        }
        m4 /= n as f32;
        let kurtosis = if variance > 1e-6 { m4 / (variance * variance) } else { 0.0 };

        // 2. Apply Hanning window and build complex FFT buffer
        let mut complex_data: Vec<Complex<f32>> = data
            .iter()
            .enumerate()
            .map(|(i, &v)| {
                let w = 0.5 * (1.0 - (2.0 * std::f32::consts::PI * i as f32
                                        / (n - 1) as f32).cos());
                Complex { re: v * w, im: 0.0 }
            })
            .collect();
        complex_data.resize(self.window_size, Complex { re: 0.0, im: 0.0 });

        let fft = self.planner.plan_fft_forward(self.window_size);
        fft.process(&mut complex_data);

        // 3. Compute PSD (first half only, one-sided)
        let half = self.window_size / 2;
        let freq_resolution = self.sample_rate / self.window_size as f32;

        // Determine notch range for motor step frequency and its harmonics
        let notch_lo = (step_freq_hz - NOTCH_HALF_BW).max(1.0);
        let notch_hi = step_freq_hz + NOTCH_HALF_BW;
        // Notch up to 3rd harmonic
        let notch_lo2 = (step_freq_hz * 2.0 - NOTCH_HALF_BW).max(1.0);
        let notch_hi2 = step_freq_hz * 2.0 + NOTCH_HALF_BW;
        let notch_lo3 = (step_freq_hz * 3.0 - NOTCH_HALF_BW).max(1.0);
        let notch_hi3 = step_freq_hz * 3.0 + NOTCH_HALF_BW;

        let mut max_mag  = 0.0f32;
        let mut peak_bin = 1usize;

        for i in 1..half {
            let freq = i as f32 * freq_resolution;
            // Skip notched motor-step frequency bins
            if step_freq_hz > 1.0 {
                if (freq >= notch_lo && freq <= notch_hi)
                    || (freq >= notch_lo2 && freq <= notch_hi2)
                    || (freq >= notch_lo3 && freq <= notch_hi3)
                {
                    continue;
                }
            }
            let mag = complex_data[i].norm_sqr();
            if mag > max_mag {
                max_mag  = mag;
                peak_bin = i;
            }
        }

        let peak_hz = peak_bin as f32 * freq_resolution;

        // 4. Structural dynamics (mass-spring: K = M·ωₙ²)
        let assumed_mass = 0.5_f32; // kg (typical CoreXY toolhead)
        let omega_n      = 2.0 * std::f32::consts::PI * peak_hz;
        let estimated_stiffness = assumed_mass * omega_n * omega_n;

        // 5. Torque ripple proxy — energy in motor harmonic bands
        let torque_ripple = if step_freq_hz > 1.0 && variance > 1e-6 {
            // Extract RMS energy inside the motor step band (1st harmonic)
            let lo_bin = ((notch_lo / freq_resolution) as usize).max(1);
            let hi_bin = ((notch_hi / freq_resolution) as usize).min(half - 1);
            let mut band_energy = 0.0f32;
            for i in lo_bin..=hi_bin {
                band_energy += complex_data[i].norm_sqr();
            }
            (band_energy / self.window_size as f32).sqrt()
        } else {
            rms * 0.05 * (kurtosis / 3.0).min(2.0)
        };

        DspResult {
            peak_hz,
            max_magnitude: max_mag.sqrt() / self.window_size as f32,
            kurtosis,
            rms,
            estimated_stiffness,
            estimated_mass: assumed_mass,
            torque_ripple,
            notched_hz: if step_freq_hz > 1.0 { step_freq_hz } else { 0.0 },
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Resonance CSV Analyser — used by the CLI mode (Step 3)
// ─────────────────────────────────────────────────────────────────────────────

/// Result from analysing a Klipper TEST_RESONANCES CSV export.
#[derive(Debug, serde::Serialize)]
pub struct ShaperRecommendation {
    pub axis:         String,
    pub peak_hz:      f32,
    pub rms:          f32,
    /// Suggested Klipper shaper type
    pub shaper_type:  String,
    /// Suggested shaper frequency (Hz)
    pub shaper_freq:  f32,
    /// Damping ratio estimate ζ
    pub damping_ratio: f32,
    /// Estimated vibration reduction factor vs. no shaper
    pub reduction_db: f32,
}

/// Parse a Klipper resonance CSV and return a shaper recommendation.
/// CSV format (Klipper ≥ 0.11):
///   freq,psd_x,psd_y,psd_z,psd_xyz
pub fn analyse_resonance_csv(path: &str, axis: &str) -> Result<ShaperRecommendation, String> {
    use std::io::{BufRead, BufReader};
    use std::fs::File;

    let file = File::open(path).map_err(|e| format!("Cannot open {}: {}", path, e))?;
    let reader = BufReader::new(file);

    let mut freqs:    Vec<f32> = Vec::new();
    let mut psd_vals: Vec<f32> = Vec::new();

    for (line_no, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("Read error at line {}: {}", line_no, e))?;
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with("freq") {
            continue; // skip header / comments
        }
        let cols: Vec<&str> = trimmed.split(',').collect();
        if cols.len() < 2 {
            continue;
        }
        let freq: f32 = cols[0].trim().parse()
            .map_err(|_| format!("Bad frequency at line {}: '{}'", line_no, cols[0]))?;
        // Select axis column: x=1, y=2, z=3, xyz=4 (default to xyz=4)
        let col_idx = match axis.to_lowercase().as_str() {
            "x"   => 1,
            "y"   => 2,
            "z"   => 3,
            _     => if cols.len() >= 5 { 4 } else { cols.len() - 1 },
        };
        let psd: f32 = cols.get(col_idx)
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0.0);
        freqs.push(freq);
        psd_vals.push(psd);
    }

    if freqs.is_empty() {
        return Err("No valid data rows found in CSV".to_string());
    }

    // Find dominant peak
    let (peak_idx, &peak_psd) = psd_vals.iter().enumerate()
        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
        .unwrap();
    let peak_hz = freqs[peak_idx];

    // Estimate bandwidth at half-power (-3 dB) for damping ratio
    let half_power = peak_psd * 0.5;
    let mut lo_hz = peak_hz;
    let mut hi_hz = peak_hz;
    for i in (0..peak_idx).rev() {
        if psd_vals[i] <= half_power { lo_hz = freqs[i]; break; }
    }
    for i in (peak_idx + 1)..freqs.len() {
        if psd_vals[i] <= half_power { hi_hz = freqs[i]; break; }
    }
    let bandwidth     = (hi_hz - lo_hz).max(0.1);
    let damping_ratio = (bandwidth / (2.0 * peak_hz)).clamp(0.01, 0.5);

    // RMS of PSD
    let rms: f32 = (psd_vals.iter().map(|&v| v * v).sum::<f32>() / psd_vals.len() as f32).sqrt();

    // Choose optimal Klipper shaper type based on damping ratio
    // ZV:      ζ < 0.05  — lightly damped systems
    // MZV:     0.05–0.12 — typical printer frames
    // EI:      0.12–0.20 — stiffer frames with moderate damping
    // 2HUMP_EI: > 0.20   — highly damped / flexible systems
    let (shaper_type, shaper_freq, reduction_db) = if damping_ratio < 0.05 {
        ("zv".to_string(),       peak_hz * 0.98, 20.0)
    } else if damping_ratio < 0.12 {
        ("mzv".to_string(),      peak_hz * 0.97, 25.0)
    } else if damping_ratio < 0.20 {
        ("ei".to_string(),       peak_hz * 0.96, 28.0)
    } else {
        ("2hump_ei".to_string(), peak_hz * 0.95, 32.0)
    };

    Ok(ShaperRecommendation {
        axis:         axis.to_string(),
        peak_hz,
        rms,
        shaper_type,
        shaper_freq,
        damping_ratio,
        reduction_db,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// Unit tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fast_path_detects_spike() {
        let mut det = FastPathDetector::new(32);
        // 5g spike on X
        let xs: Vec<f32> = (0..32).map(|i| if i == 5 { 5.0 } else { 0.01 }).collect();
        let ys: Vec<f32> = vec![0.01; 32];
        let zs: Vec<f32> = vec![0.01; 32];
        let evt = det.feed(&xs, &ys, &zs);
        assert!(evt.is_some());
        let e = evt.unwrap();
        assert!(e.peak_g > 4.5);
        assert_eq!(e.axis, "x");
    }

    #[test]
    fn fast_path_debounces() {
        let mut det = FastPathDetector::new(32);
        det.last_event_time = std::time::Instant::now(); // reset to now
        let xs: Vec<f32> = vec![6.0; 32];
        let ys: Vec<f32> = vec![0.0; 32];
        let zs: Vec<f32> = vec![0.0; 32];
        // Feed within debounce window — should be None
        let evt = det.feed(&xs, &ys, &zs);
        assert!(evt.is_none());
    }

    #[test]
    fn fast_path_no_false_positive_on_noise() {
        let mut det = FastPathDetector::new(32);
        let xs: Vec<f32> = (0..32).map(|i| (i as f32 * 0.01).sin() * 0.05).collect();
        let ys = xs.clone();
        let zs: Vec<f32> = vec![0.02; 32];
        let evt = det.feed(&xs, &ys, &zs);
        assert!(evt.is_none());
    }

    #[test]
    fn slow_path_peak_hz() {
        let mut proc = SlowPathProcessor::new(3200, 3200.0);
        // Inject a pure 45 Hz sine at 3200 Hz sample rate
        let data: Vec<f32> = (0..3200)
            .map(|i| (2.0 * std::f32::consts::PI * 45.0 * i as f32 / 3200.0).sin())
            .collect();
        let result = proc.process_window(&data, 0.0);
        // Peak should be within ±2 Hz of 45 Hz
        assert!((result.peak_hz - 45.0).abs() < 2.0,
                "Expected ~45 Hz, got {} Hz", result.peak_hz);
    }

    #[test]
    fn slow_path_notch_masks_motor_freq() {
        let mut proc = SlowPathProcessor::new(3200, 3200.0);
        // Strong 80 Hz motor excitation + weaker 45 Hz resonance
        let data: Vec<f32> = (0..3200)
            .map(|i| {
                let t = i as f32 / 3200.0;
                (2.0 * std::f32::consts::PI * 80.0 * t).sin() * 3.0
                    + (2.0 * std::f32::consts::PI * 45.0 * t).sin() * 1.0
            })
            .collect();
        let result = proc.process_window(&data, 80.0); // tell DSP motor runs at 80 Hz
        // After notching 80 Hz, peak should shift toward 45 Hz
        assert!((result.peak_hz - 45.0).abs() < 5.0,
                "After notch, expected ~45 Hz, got {} Hz", result.peak_hz);
        assert_eq!(result.notched_hz, 80.0);
    }
}
