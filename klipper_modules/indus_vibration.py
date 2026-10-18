# Klipper extra module to stream ADXL345 data over UDP to the Indus3D Rust DSP
#
# To install:
# ln -s ~/Indus3D/klipper_modules/indus_vibration.py ~/klipper/klippy/extras/indus_vibration.py
#
# In printer.cfg:
# [indus_vibration]
# udp_host: 127.0.0.1
# udp_port: 3200
# binary_mode: True   (optional, default True — use binary packets)

import socket
import logging
import struct

class IndusVibrationClient:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.udp_host = config.get("udp_host", "127.0.0.1")
        self.udp_port = config.getint("udp_port", 3200)
        self.binary_mode = config.getboolean("binary_mode", True)
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('INDUS_VIBRATION_START', self.cmd_START,
                                    desc="Start streaming ADXL data to Indus3D")
        self.gcode.register_command('INDUS_VIBRATION_STOP', self.cmd_STOP,
                                    desc="Stop streaming ADXL data")
                                    
        self.active_chips = {}

    def _get_chip(self, chip_name):
        chip_name = chip_name.strip()
        obj_name = f"adxl345 {chip_name}" if chip_name else "adxl345"
        return self.printer.lookup_object(obj_name)

    def cmd_START(self, gcmd):
        chip_name = gcmd.get('CHIP', '')
        try:
            chip = self._get_chip(chip_name)
        except Exception:
            raise gcmd.error(f"Unknown accelerometer chip '{chip_name}'")
            
        if chip_name in self.active_chips:
            gcmd.respond_info(f"Already streaming from {chip_name or 'default'}")
            return
            
        # Create a client object that Klipper will call with batches of data
        client = ADXLUDPStreamer(self.sock, self.udp_host, self.udp_port,
                                 binary=self.binary_mode)
        
        # Start Klipper's bulk sensor measurement
        # Klipper's ADXL345 class exposes 'setup_measure_client' or we can just 
        # add a client via the standard API. For resonance testing, Klipper uses:
        chip.add_client(client)
        chip.start_measure()
        
        self.active_chips[chip_name] = (chip, client)
        gcmd.respond_info(f"Indus3D: UDP vibration stream started for {chip_name or 'default'} at {self.udp_host}:{self.udp_port}")

    def cmd_STOP(self, gcmd):
        chip_name = gcmd.get('CHIP', '')
        if chip_name not in self.active_chips:
            return
            
        chip, client = self.active_chips.pop(chip_name)
        chip.remove_client(client)
        gcmd.respond_info(f"Indus3D: UDP vibration stream stopped for {chip_name or 'default'}")

class ADXLUDPStreamer:
    # ADC scale: ADXL345 ±16g full-scale → 0.0039 g per raw count
    _SCALE = 0.0039
    # Binary packet magic prefix
    _MAGIC = b"IDX"
    # Per-sample binary struct: f32 timestamp, i16 x, i16 y, i16 z, u32 padding (14 bytes)
    _SAMPLE_FMT = "<fhhhI"
    _SAMPLE_SIZE = struct.calcsize(_SAMPLE_FMT)  # 14 bytes

    def __init__(self, sock, host, port, binary=True):
        self.sock = sock
        self.addr = (host, port)
        self.name = "indus_vibration_client"
        self.binary = binary

    def process_batch(self, eventtime, batch):
        """Called by Klipper with each new batch of ADXL samples.

        Each sample is (time, x_g, y_g, z_g) in physical units (g).
        In binary mode the whole batch is packed into one UDP datagram:
            3 bytes magic 'IDX' + N × 14-byte sample structs
        In CSV mode (fallback) each sample is a comma-separated text line.
        """
        if not batch:
            return
        if self.binary:
            self._send_binary(batch)
        else:
            self._send_csv(batch)

    def _send_binary(self, batch):
        """Pack samples as IDX magic + per-sample little-endian structs."""
        buf = bytearray(self._MAGIC)
        for sample in batch:
            if len(sample) < 4:
                continue
            t, x, y, z = float(sample[0]), float(sample[1]), float(sample[2]), float(sample[3])
            # Convert from g to raw ADC counts (clamp to i16 range)
            xi = max(-32768, min(32767, int(round(x / self._SCALE))))
            yi = max(-32768, min(32767, int(round(y / self._SCALE))))
            zi = max(-32768, min(32767, int(round(z / self._SCALE))))
            buf += struct.pack(self._SAMPLE_FMT, t, xi, yi, zi, 0)
        if len(buf) > len(self._MAGIC):  # at least one valid sample
            try:
                self.sock.sendto(bytes(buf), self.addr)
            except Exception:
                pass  # UDP fire-and-forget

    def _send_csv(self, batch):
        """Legacy CSV fallback: one line per sample, tab/comma separated."""
        output = []
        for sample in batch:
            if len(sample) >= 4:
                t, x, y, z = sample[0], sample[1], sample[2], sample[3]
                output.append(f"{t:.6f},{x:.2f},{y:.2f},{z:.2f}\n")
        if output:
            try:
                self.sock.sendto("".join(output).encode("utf-8"), self.addr)
            except Exception:
                pass

def load_config(config):
    return IndusVibrationClient(config)
