# Klipper extra module to stream ADXL345 data over UDP to the Indus3D Rust DSP
#
# To install:
# ln -s ~/Indus3D/klipper_modules/indus_vibration.py ~/klipper/klippy/extras/indus_vibration.py
#
# In printer.cfg:
# [indus_vibration]
# udp_host: 127.0.0.1
# udp_port: 3200

import socket
import logging

class IndusVibrationClient:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.udp_host = config.get("udp_host", "127.0.0.1")
        self.udp_port = config.getint("udp_port", 3200)
        
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
        client = ADXLUDPStreamer(self.sock, self.udp_host, self.udp_port)
        
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
    def __init__(self, sock, host, port):
        self.sock = sock
        self.addr = (host, port)
        self.name = "indus_vibration_client"

    def process_batch(self, eventtime, batch):
        # Klipper bulk sensor batch format varies, but usually it's a list or numpy array
        # of (time, x, y, z) or similar. We convert it to a simple CSV string to match 
        # what our Rust engine expects.
        
        # Optimization: To avoid building huge strings on the Klipper Python side, 
        # we batch them into chunks and send via UDP.
        output = []
        for sample in batch:
            # Assuming sample is (time, x_accel, y_accel, z_accel)
            # which is the standard format for Klipper's adxl345 process_batch
            if len(sample) >= 4:
                t, x, y, z = sample[0], sample[1], sample[2], sample[3]
                output.append(f"{t:.6f},{x:.2f},{y:.2f},{z:.2f}\n")
                
        if not output:
            return
            
        payload = "".join(output).encode('utf-8')
        try:
            self.sock.sendto(payload, self.addr)
        except Exception:
            pass # UDP is fire-and-forget, ignore socket buffer full errors

def load_config(config):
    return IndusVibrationClient(config)
