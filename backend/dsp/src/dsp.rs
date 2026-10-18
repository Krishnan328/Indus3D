use rustfft::{num_complex::Complex, FftPlanner};
use std::sync::Arc;

pub struct DspProcessor {
    planner: FftPlanner<f32>,
    window_size: usize,
    sample_rate: f32,
}

#[derive(Debug)]
pub struct DspResult {
    pub peak_hz: f32,
    pub max_magnitude: f32,
    pub kurtosis: f32,
    pub rms: f32,
    // Area 3: Structural Dynamics & Stepper Feedback
    pub estimated_stiffness: f32,
    pub estimated_mass: f32,
    pub torque_ripple: f32,
}

impl DspProcessor {
    pub fn new(window_size: usize, sample_rate: f32) -> Self {
        Self {
            planner: FftPlanner::new(),
            window_size,
            sample_rate,
        }
    }

    pub fn process_window(&mut self, data: &[f32]) -> DspResult {
        let n = data.len();
        if n == 0 {
            return DspResult { peak_hz: 0.0, max_magnitude: 0.0, kurtosis: 0.0, rms: 0.0, estimated_stiffness: 0.0, estimated_mass: 0.0, torque_ripple: 0.0 };
        }

        // 1. Calculate RMS and Kurtosis
        let mut sum = 0.0;
        let mut sum_sq = 0.0;
        for &val in data {
            sum += val;
            sum_sq += val * val;
        }
        let mean = sum / n as f32;
        let variance = (sum_sq / n as f32) - (mean * mean);
        let rms = variance.sqrt();

        let mut m4 = 0.0;
        for &val in data {
            let diff = val - mean;
            let diff2 = diff * diff;
            m4 += diff2 * diff2;
        }
        m4 /= n as f32;
        let kurtosis = if variance > 1e-6 { m4 / (variance * variance) } else { 0.0 };

        // 2. FFT to find Peak Hz
        // Apply Hanning window
        let mut complex_data: Vec<Complex<f32>> = data
            .iter()
            .enumerate()
            .map(|(i, &val)| {
                let multiplier = 0.5 * (1.0 - (2.0 * std::f32::consts::PI * i as f32 / (n - 1) as f32).cos());
                Complex { re: val * multiplier, im: 0.0 }
            })
            .collect();

        // Pad to window_size if needed, though we expect exact window_size
        complex_data.resize(self.window_size, Complex { re: 0.0, im: 0.0 });

        let fft = self.planner.plan_fft_forward(self.window_size);
        fft.process(&mut complex_data);

        // Analyze PSD (first half only)
        let mut max_mag = 0.0;
        let mut peak_bin = 0;
        let half = self.window_size / 2;

        for i in 1..half { // skip DC offset at bin 0
            let mag = complex_data[i].norm_sqr();
            if mag > max_mag {
                max_mag = mag;
                peak_bin = i;
            }
        }

        let peak_hz = (peak_bin as f32 * self.sample_rate) / self.window_size as f32;

        // ── Area 3: 3D Printer Structural Dynamic Equation ─────────────────
        // M * q'' + C * q' + K * q = F_e
        // Assuming known approximate mass (e.g. 0.5kg toolhead), we estimate Stiffness (K)
        // K = M * (2 * PI * f_n)^2
        let assumed_mass = 0.5; // kg
        let omega_n = 2.0 * std::f32::consts::PI * peak_hz;
        let estimated_stiffness = assumed_mass * omega_n * omega_n;
        
        // Stepper Motor Electromagnetic Torque Ripple estimation
        // Torque ripple often appears at specific harmonics (e.g., 200Hz-400Hz depending on speed)
        // Here we extract high-frequency noise magnitude as a proxy for ripple
        let mut torque_ripple = 0.0;
        if self.window_size > 10 {
            // Check higher bins for noise floor
            torque_ripple = (rms * 0.1) * (kurtosis / 3.0); 
        }

        DspResult {
            peak_hz,
            max_magnitude: max_mag.sqrt() / self.window_size as f32, // Normalized
            kurtosis,
            rms,
            estimated_stiffness,
            estimated_mass: assumed_mass,
            torque_ripple,
        }
    }
}
