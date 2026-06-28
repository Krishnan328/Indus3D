from queue import PriorityQueue
import time, uuid

class CommandQueue:
    def __init__(self): self.queue=PriorityQueue()

    def create_command(self, gcode, source="user", priority=1):
        if any(f in gcode for f in ["M112","FIRMWARE_RESTART"]):
            raise ValueError("Unsafe command blocked")
        return {"id":str(uuid.uuid4()),"gcode":gcode,"source":source,"priority":priority,"timestamp":time.time()}

    def enqueue(self, command): self.queue.put((-command["priority"],command))

    def dequeue(self):
        if self.queue.empty(): return None
        _,cmd=self.queue.get(); return cmd

    def is_empty(self): return self.queue.empty()
