import threading, time
from services.moonraker_client import MoonrakerClient
from core.logger import log_command

class QueueWorker:
    def __init__(self, command_queue):
        self.queue=command_queue; self.client=MoonrakerClient(); self.running=True

    def start(self):
        threading.Thread(target=self.run,daemon=True).start()

    def run(self):
        print("🚀 Command Queue Worker started")
        while self.running:
            if not self.queue.is_empty():
                cmd=self.queue.dequeue()
                print(f"⚡ Executing: {cmd['gcode']} (source: {cmd['source']})")
                state,msg=self.client.get_printer_state()
                if state not in ["ready","idle"]:
                    print("⛔ Printer not ready."); log_command(cmd["gcode"],cmd["source"],"blocked"); continue
                success=self.client.send_gcode(cmd["gcode"])
                log_command(cmd["gcode"],cmd["source"],"executed" if success else "failed")
            time.sleep(0.05)
