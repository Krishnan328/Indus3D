import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
spec = importlib.util.spec_from_file_location("observe_print", LAB / "observe_print.py")
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ObserverTests(unittest.TestCase):
    def test_api_state_alias_and_duplicate_sample(self):
        with sqlite3.connect(":memory:") as conn:
            observer.initialize(conn)
            sample = {"telemetry": {"state": "printing"}, "monotonic_seconds": 1}
            self.assertEqual(observer.ingest(conn, 1, sample), "printing")
            observer.ingest(conn, 1, sample)
            observer.ingest(conn, 2, {"telemetry": {"state": "complete"}})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT detail FROM events ORDER BY id DESC LIMIT 1").fetchone()[0], "printing -> complete")


if __name__ == "__main__":
    unittest.main()
