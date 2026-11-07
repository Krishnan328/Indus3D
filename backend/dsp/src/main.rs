// dsp/src/main.rs — Indus3D ADXL DSP Pipeline entry point
//
// Two runtime modes:
//
//   DAEMON MODE  (default, no --analyze-csv flag)
//   ─────────────────────────────────────────────
//   • Listens on UDP 3200 for raw ADXL samples from Klipper
//     (either binary struct or legacy CSV, auto-detected per packet)
//   • Fast-path collision detector runs on every small batch — emits
//     CollisionEvent JSON to UDP 3202 for instant Python/Moonraker response
//   • Slow-path 1-second Hanning+FFT window emits telemetry JSON to UDP 3201
//   • Accepts velocity metadata packets on UDP 3203 so the notch filter knows
//     the current motor step frequency
//
//   ANALYSER MODE  (--analyze-csv <file> [--axis x|y|z|xyz])
//   ──────────────────────────────────────────────────────────
//   • Parses a Klipper TEST_RESONANCES CSV in < 50 ms
//   • Prints a JSON shaper recommendation to stdout
//   • Used by core/shaper_tuner.py as a subprocess for guided calibration

mod dsp;

use dsp::{FastPathDetector, SlowPathProcessor, analyse_resonance_csv};
use std::net::UdpSocket;
use std::time::Duration;
use byteorder::{LittleEndian, ReadBytesExt};
use std::io::Cursor;
use clap::Parser;

// ─────────────────────────────────────────────────────────────────────────────
// CLI definition (clap)
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Parser, Debug)]
#[command(name = "indus3d-dsp", version = "0.2.0",
          about = "Indus3D ADXL accelerometer DSP pipeline & resonance analyser")]
struct Cli {
    /// Path to a Klipper TEST_RESONANCES CSV to analyse and then exit
    #[arg(long, value_name = "FILE")]
    analyze_csv: Option<String>,

    /// Axis for CSV analysis (x, y, z, or xyz)
    #[arg(long, default_value = "xyz")]
    axis: String,

    /// UDP port to listen for raw ADXL samples from Klipper
    #[arg(long, default_value_t = 3200)]
    in_port: u16,

    /// UDP port for 1-Hz spectral telemetry JSON (slow path)
    #[arg(long, default_value_t = 3201)]
    out_port: u16,

    /// UDP port for instant collision events (fast path)
    #[arg(long, default_value_t = 3202)]
    collision_port: u16,

    /// UDP port for receiving velocity metadata from Python
    #[arg(long, default_value_t = 3203)]
    meta_port: u16,
}

// ─────────────────────────────────────────────────────────────────────────────
// Binary packet format (Step 2)
// Each sample is a fixed 14-byte little-endian struct:
//   f32 timestamp (4 bytes)
//   i16 x_raw     (2 bytes)  — raw ADC counts
//   i16 y_raw     (2 bytes)
//   i16 z_raw     (2 bytes)
//   u32 _padding  (4 bytes)  — future use / alignment
//
// Scale factor: 1 count = 0.0039 g  (ADXL345 full-scale ±16g, 12-bit signed)
// ─────────────────────────────────────────────────────────────────────────────

const BINARY_PACKET_MAGIC: &[u8] = b"IDX"; // first 3 bytes identify binary packets
const SCALE_G: f32 = 0.0039;               // g per ADC count
const SAMPLE_BYTES: usize = 14;

#[allow(dead_code)]
struct AdxlSample {
    timestamp: f32,
    x: f32,
    y: f32,
    z: f32,
}

/// Try to parse binary-format ADXL packet.
/// Returns None if the packet does not start with the BINARY_PACKET_MAGIC.
fn parse_binary_packet(buf: &[u8]) -> Option<Vec<AdxlSample>> {
    if buf.len() < BINARY_PACKET_MAGIC.len() || &buf[..3] != BINARY_PACKET_MAGIC {
        return None;
    }
    let payload = &buf[3..];
    if payload.len() % SAMPLE_BYTES != 0 {
        return None;
    }
    let count = payload.len() / SAMPLE_BYTES;
    let mut samples = Vec::with_capacity(count);
    for i in 0..count {
        let chunk = &payload[i * SAMPLE_BYTES..(i + 1) * SAMPLE_BYTES];
        let mut cur = Cursor::new(chunk);
        let timestamp = cur.read_f32::<LittleEndian>().ok()?;
        let x_raw     = cur.read_i16::<LittleEndian>().ok()?;
        let y_raw     = cur.read_i16::<LittleEndian>().ok()?;
        let z_raw     = cur.read_i16::<LittleEndian>().ok()?;
        samples.push(AdxlSample {
            timestamp,
            x: x_raw as f32 * SCALE_G,
            y: y_raw as f32 * SCALE_G,
            z: z_raw as f32 * SCALE_G,
        });
    }
    Some(samples)
}

/// Parse legacy CSV format: "timestamp,x,y,z\n..."
fn parse_csv_packet(buf: &[u8]) -> Vec<AdxlSample> {
    let text = String::from_utf8_lossy(buf);
    let mut samples = Vec::new();
    for line in text.lines() {
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() >= 4 {
            if let (Ok(t), Ok(x), Ok(y), Ok(z)) = (
                parts[0].parse::<f32>(),
                parts[1].parse::<f32>(),
                parts[2].parse::<f32>(),
                parts[3].parse::<f32>(),
            ) {
                samples.push(AdxlSample { timestamp: t, x, y, z });
            }
        }
    }
    samples
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

fn main() -> std::io::Result<()> {
    let cli = Cli::parse();

    // ── ANALYSER MODE ─────────────────────────────────────────────────────────
    if let Some(csv_path) = cli.analyze_csv {
        eprintln!("🔬 Indus3D DSP — Resonance Analyser mode");
        eprintln!("   CSV:  {}", csv_path);
        eprintln!("   Axis: {}", cli.axis);
        match analyse_resonance_csv(&csv_path, &cli.axis) {
            Ok(rec) => {
                let json = serde_json::to_string_pretty(&rec).unwrap();
                println!("{}", json);
            }
            Err(e) => {
                eprintln!("❌ Analysis error: {}", e);
                // Emit error as JSON so shaper_tuner.py can catch it
                let err_json = serde_json::json!({"error": e});
                println!("{}", serde_json::to_string_pretty(&err_json).unwrap());
                std::process::exit(1);
            }
        }
        return Ok(());
    }

    // ── DAEMON MODE ───────────────────────────────────────────────────────────
    println!("🚀 Indus3D Rust DSP Pipeline v0.2.0 starting (daemon mode)");

    const SAMPLE_RATE: f32 = 3200.0;
    const WINDOW_SIZE: usize = 3200; // 1-second window

    // Ingestion socket: raw ADXL samples from Klipper (binary or CSV)
    let in_sock = UdpSocket::bind(format!("127.0.0.1:{}", cli.in_port))?;
    in_sock.set_read_timeout(Some(Duration::from_millis(200)))?;
    println!("📡 Listening for ADXL samples on 127.0.0.1:{} (binary+CSV)", cli.in_port);

    // Output socket: 1-Hz spectral telemetry
    let out_sock    = UdpSocket::bind("127.0.0.1:0")?;
    let telemetry_addr = format!("127.0.0.1:{}", cli.out_port);

    // Collision output socket: instant impact events
    let col_sock    = UdpSocket::bind("127.0.0.1:0")?;
    let collision_addr = format!("127.0.0.1:{}", cli.collision_port);

    // Velocity metadata socket: receives {"vx":N,"vy":N,"steps_mm":N} from Python
    let meta_sock = UdpSocket::bind(format!("127.0.0.1:{}", cli.meta_port))?;
    meta_sock.set_read_timeout(Some(Duration::from_millis(1)))?;
    println!("📡 Velocity metadata on 127.0.0.1:{}", cli.meta_port);
    println!("📡 Slow-path telemetry → 127.0.0.1:{}", cli.out_port);
    println!("📡 Fast-path collisions → 127.0.0.1:{}", cli.collision_port);

    let mut fast_path = FastPathDetector::new(64);
    let mut slow_x = SlowPathProcessor::new(WINDOW_SIZE, SAMPLE_RATE);
    let mut slow_y = SlowPathProcessor::new(WINDOW_SIZE, SAMPLE_RATE);
    let mut slow_z = SlowPathProcessor::new(WINDOW_SIZE, SAMPLE_RATE);

    let mut buf_x: Vec<f32> = Vec::with_capacity(WINDOW_SIZE);
    let mut buf_y: Vec<f32> = Vec::with_capacity(WINDOW_SIZE);
    let mut buf_z: Vec<f32> = Vec::with_capacity(WINDOW_SIZE);

    let mut recv_buf  = vec![0u8; 4096];
    let mut meta_buf  = vec![0u8; 256];

    // Current motor step frequency (updated from meta socket)
    let mut step_freq_hz: f32 = 0.0;

    loop {
        // ── Non-blocking: drain velocity metadata socket ───────────────────
        loop {
            match meta_sock.recv_from(&mut meta_buf) {
                Ok((n, _)) => {
                    if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&meta_buf[..n]) {
                        let vx: f32 = v.get("vx").and_then(|x| x.as_f64()).unwrap_or(0.0) as f32;
                        let vy: f32 = v.get("vy").and_then(|x| x.as_f64()).unwrap_or(0.0) as f32;
                        let steps_mm: f32 = v.get("steps_mm").and_then(|x| x.as_f64()).unwrap_or(80.0) as f32;
                        let v_total = (vx * vx + vy * vy).sqrt();
                        step_freq_hz = v_total * steps_mm; // f_step = v * steps/mm
                    }
                }
                Err(_) => break,
            }
        }

        // ── Block on ADXL ingestion socket ────────────────────────────────
        match in_sock.recv_from(&mut recv_buf) {
            Ok((amt, _)) => {
                let raw = &recv_buf[..amt];

                // Auto-detect binary vs CSV
                let samples = if let Some(s) = parse_binary_packet(raw) {
                    s
                } else {
                    parse_csv_packet(raw)
                };

                if samples.is_empty() {
                    continue;
                }

                // ── FAST PATH: per-batch collision detection (Step 1) ──────
                {
                    let xs: Vec<f32> = samples.iter().map(|s| s.x).collect();
                    let ys: Vec<f32> = samples.iter().map(|s| s.y).collect();
                    let zs: Vec<f32> = samples.iter().map(|s| s.z).collect();

                    if let Some(event) = fast_path.feed(&xs, &ys, &zs) {
                        if let Ok(msg) = serde_json::to_string(&event) {
                            let _ = col_sock.send_to(msg.as_bytes(), &collision_addr);
                            eprintln!("🚨 COLLISION: {}", event.reason);
                        }
                    }

                    // Accumulate into slow-path buffers
                    buf_x.extend_from_slice(&xs);
                    buf_y.extend_from_slice(&ys);
                    buf_z.extend_from_slice(&zs);
                }

                // ── SLOW PATH: Hanning FFT with motor notch (Step 2&3) ────
                if buf_x.len() >= WINDOW_SIZE {
                    let res_x = slow_x.process_window(&buf_x[..WINDOW_SIZE], step_freq_hz);
                    let res_y = slow_y.process_window(&buf_y[..WINDOW_SIZE], step_freq_hz);
                    let res_z = slow_z.process_window(&buf_z[..WINDOW_SIZE], step_freq_hz);

                    let payload = serde_json::json!({
                        "x": {
                            "hz": res_x.peak_hz, "mag": res_x.max_magnitude,
                            "kurtosis": res_x.kurtosis, "rms": res_x.rms,
                            "stiffness": res_x.estimated_stiffness,
                            "mass": res_x.estimated_mass,
                            "torque_ripple": res_x.torque_ripple,
                            "notched_hz": res_x.notched_hz,
                        },
                        "y": {
                            "hz": res_y.peak_hz, "mag": res_y.max_magnitude,
                            "kurtosis": res_y.kurtosis, "rms": res_y.rms,
                            "stiffness": res_y.estimated_stiffness,
                            "mass": res_y.estimated_mass,
                            "torque_ripple": res_y.torque_ripple,
                            "notched_hz": res_y.notched_hz,
                        },
                        "z": {
                            "hz": res_z.peak_hz, "mag": res_z.max_magnitude,
                            "kurtosis": res_z.kurtosis, "rms": res_z.rms,
                            "stiffness": res_z.estimated_stiffness,
                            "mass": res_z.estimated_mass,
                            "torque_ripple": res_z.torque_ripple,
                            "notched_hz": res_z.notched_hz,
                        },
                        "step_freq_hz": step_freq_hz,
                    });

                    if let Ok(msg) = serde_json::to_string(&payload) {
                        let _ = out_sock.send_to(msg.as_bytes(), &telemetry_addr);
                    }

                    // 50% overlapping window
                    let overlap = WINDOW_SIZE / 2;
                    buf_x.drain(0..overlap);
                    buf_y.drain(0..overlap);
                    buf_z.drain(0..overlap);
                }
            }
            Err(e) => {
                let k = e.kind();
                if k != std::io::ErrorKind::WouldBlock && k != std::io::ErrorKind::TimedOut {
                    eprintln!("⚠️  Socket error: {}", e);
                }
            }
        }
    }
}
