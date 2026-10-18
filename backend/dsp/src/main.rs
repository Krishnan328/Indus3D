use std::net::UdpSocket;
use std::sync::{Arc, Mutex};
use serde::Serialize;
use std::time::Duration;

mod dsp;
use dsp::DspProcessor;

const SAMPLE_RATE: f32 = 3200.0;
const WINDOW_SIZE: usize = 3200; // 1 second window

#[derive(Serialize)]
struct TelemetryPayload {
    axis: String,
    peak_hz: f32,
    magnitude: f32,
    kurtosis: f32,
    rms: f32,
}

fn main() -> std::io::Result<()> {
    println!("🚀 Indus3D Rust DSP Pipeline Starting...");
    
    // Ingestion Socket: Listen for raw ADXL data from Klipper (Batch: x,y,z as f32 array)
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
                // Expecting simple CSV strings for now: "t,x,y,z\n"
                // In production, use a binary struct for zero-parsing overhead
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

                // If we filled a 1-second window, process it!
                if buffer_x.len() >= WINDOW_SIZE {
                    let res_x = processor_x.process_window(&buffer_x);
                    let res_y = processor_y.process_window(&buffer_y);
                    let res_z = processor_z.process_window(&buffer_z);

                    let payload = serde_json::json!({
                        "x": { "hz": res_x.peak_hz, "mag": res_x.max_magnitude, "kurtosis": res_x.kurtosis, "rms": res_x.rms, "stiffness": res_x.estimated_stiffness, "mass": res_x.estimated_mass, "torque_ripple": res_x.torque_ripple },
                        "y": { "hz": res_y.peak_hz, "mag": res_y.max_magnitude, "kurtosis": res_y.kurtosis, "rms": res_y.rms, "stiffness": res_y.estimated_stiffness, "mass": res_y.estimated_mass, "torque_ripple": res_y.torque_ripple },
                        "z": { "hz": res_z.peak_hz, "mag": res_z.max_magnitude, "kurtosis": res_z.kurtosis, "rms": res_z.rms, "stiffness": res_z.estimated_stiffness, "mass": res_z.estimated_mass, "torque_ripple": res_z.torque_ripple },
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
