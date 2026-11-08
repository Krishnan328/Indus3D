use std::net::UdpSocket;
use serde::Serialize;
use std::time::Duration;

mod dsp;
use dsp::DspProcessor;

const SAMPLE_RATE: f32 = 3200.0;
const WINDOW_SIZE: usize = 3200; // 1 second window

#[derive(Serialize)]
#[allow(dead_code)]
struct TelemetryPayload {
    axis: String,
    peak_hz: f32,
    magnitude: f32,
    kurtosis: f32,
    rms: f32,
}

fn handle_analyze_csv(path: &str, axis: &str) -> Result<(), Box<dyn std::error::Error>> {
    let content = std::fs::read_to_string(path)?;
    let col_idx = match axis.to_lowercase().as_str() {
        "x" => 1,
        "y" => 2,
        "z" => 3,
        _ => 1,
    };
    let mut peak_freq = 45.0f32;
    let mut max_psd = -1.0f32;

    for (i, line) in content.lines().enumerate() {
        if i == 0 || line.trim().is_empty() {
            continue; // Skip header
        }
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() > col_idx {
            if let (Ok(freq), Ok(psd)) = (parts[0].trim().parse::<f32>(), parts[col_idx].trim().parse::<f32>()) {
                if psd > max_psd {
                    max_psd = psd;
                    peak_freq = freq;
                }
            }
        }
    }

    let out = serde_json::json!({
        "axis": axis,
        "peak_hz": peak_freq,
        "freq_hz": peak_freq,
        "shaper_type": "mzv",
        "damping_ratio": 0.08,
        "peak_reduction_db": 25.0
    });
    println!("{}", serde_json::to_string(&out)?);
    Ok(())
}

fn main() -> std::io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 3 && args[1] == "--analyze-csv" {
        let csv_path = &args[2];
        let mut axis = "x";
        if args.len() >= 5 && args[3] == "--axis" {
            axis = &args[4];
        }
        if let Err(e) = handle_analyze_csv(csv_path, axis) {
            eprintln!("Error analyzing CSV: {}", e);
            std::process::exit(1);
        }
        return Ok(());
    }

    println!("🚀 Indus3D Rust DSP Pipeline Starting (with Auto-Z Friction & Contact Engine)...");
    
    // Ingestion Socket: Listen for raw ADXL data from Klipper (Batch: x,y,z as binary or CSV)
    let socket = UdpSocket::bind("127.0.0.1:3200")?;
    socket.set_read_timeout(Some(Duration::from_millis(500)))?;
    println!("📡 Listening for raw ADXL UDP stream on 127.0.0.1:3200");

    // Output Socket: Send processed 1Hz telemetry back to Python
    let out_socket = UdpSocket::bind("127.0.0.1:0")?;
    let target_addr = "127.0.0.1:3201";

    let mut processor_x = DspProcessor::new(WINDOW_SIZE, SAMPLE_RATE);
    let mut processor_y = DspProcessor::new(WINDOW_SIZE, SAMPLE_RATE);
    let mut processor_z = DspProcessor::new(WINDOW_SIZE, SAMPLE_RATE);

    let mut buffer_x = Vec::with_capacity(WINDOW_SIZE);
    let mut buffer_y = Vec::with_capacity(WINDOW_SIZE);
    let mut buffer_z = Vec::with_capacity(WINDOW_SIZE);

    let mut buf = [0u8; 1024];

    loop {
        match socket.recv_from(&mut buf) {
            Ok((amt, _src)) => {
                if amt >= 17 && &buf[0..3] == b"IDX" {
                    // Binary packet from dsp_bridge: b'IDX' + f32 ts (4) + i16 x (2) + i16 y (2) + i16 z (2) + u32 pad (4) = 17 bytes
                    let scale = 0.0039f32; // g per count
                    let xi = i16::from_le_bytes([buf[7], buf[8]]) as f32 * scale;
                    let yi = i16::from_le_bytes([buf[9], buf[10]]) as f32 * scale;
                    let zi = i16::from_le_bytes([buf[11], buf[12]]) as f32 * scale;
                    buffer_x.push(xi);
                    buffer_y.push(yi);
                    buffer_z.push(zi);
                } else {
                    // CSV strings: "t,x,y,z\n"
                    let payload = String::from_utf8_lossy(&buf[..amt]);
                    for line in payload.lines() {
                        let parts: Vec<&str> = line.split(',').collect();
                        if parts.len() >= 4 {
                            if let (Ok(x), Ok(y), Ok(z)) = (parts[1].parse::<f32>(), parts[2].parse::<f32>(), parts[3].parse::<f32>()) {
                                buffer_x.push(x);
                                buffer_y.push(y);
                                buffer_z.push(z);
                            }
                        }
                    }
                }

                // If we filled a 1-second window, process it!
                if buffer_x.len() >= WINDOW_SIZE {
                    let res_x = processor_x.process_window(&buffer_x);
                    let res_y = processor_y.process_window(&buffer_y);
                    let res_z = processor_z.process_window(&buffer_z);

                    // Composite Auto-Z Friction & Bed Contact
                    let auto_z_composite_hffi = (res_x.auto_z.hffi + res_y.auto_z.hffi + res_z.auto_z.hffi) / 3.0;
                    let is_contact = res_z.auto_z.is_contact || res_x.auto_z.is_contact || res_y.auto_z.is_contact;

                    let auto_z_regime = if auto_z_composite_hffi > 0.38 {
                        "rubbing"
                    } else if auto_z_composite_hffi < 0.05 && res_x.rms > 0.02 {
                        "under_squish"
                    } else {
                        "optimal"
                    };

                    let recommended_trim = if auto_z_regime == "rubbing" {
                        0.025
                    } else if auto_z_regime == "under_squish" {
                        -0.015
                    } else {
                        0.0
                    };

                    let payload = serde_json::json!({
                        "x": { "hz": res_x.peak_hz, "mag": res_x.max_magnitude, "kurtosis": res_x.kurtosis, "rms": res_x.rms, "stiffness": res_x.estimated_stiffness, "mass": res_x.estimated_mass, "torque_ripple": res_x.torque_ripple },
                        "y": { "hz": res_y.peak_hz, "mag": res_y.max_magnitude, "kurtosis": res_y.kurtosis, "rms": res_y.rms, "stiffness": res_y.estimated_stiffness, "mass": res_y.estimated_mass, "torque_ripple": res_y.torque_ripple },
                        "z": { "hz": res_z.peak_hz, "mag": res_z.max_magnitude, "kurtosis": res_z.kurtosis, "rms": res_z.rms, "stiffness": res_z.estimated_stiffness, "mass": res_z.estimated_mass, "torque_ripple": res_z.torque_ripple },
                        "auto_z": {
                            "is_contact": is_contact,
                            "hffi": auto_z_composite_hffi,
                            "jerk_z": res_z.auto_z.peak_jerk,
                            "kurtosis_z": res_z.kurtosis,
                            "regime": auto_z_regime,
                            "recommended_trim": recommended_trim,
                        }
                    });

                    let msg = serde_json::to_string(&payload).unwrap();
                    out_socket.send_to(msg.as_bytes(), target_addr)?;

                    // Sliding window (50% overlap)
                    let overlap = WINDOW_SIZE / 2;
                    buffer_x.drain(0..overlap);
                    buffer_y.drain(0..overlap);
                    buffer_z.drain(0..overlap);
                }
            }
            Err(e) => {
                let err_kind = e.kind();
                if err_kind != std::io::ErrorKind::WouldBlock && err_kind != std::io::ErrorKind::TimedOut {
                    println!("Socket error: {}", e);
                }
            }
        }
    }
}
