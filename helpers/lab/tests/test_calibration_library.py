"""Regression tests for review-only calibration artifacts (no printer needed)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION = ROOT / "calibration"
GENERATOR = CALIBRATION / "generate_calibration_test.py"
VALIDATOR = CALIBRATION / "validate_calibration_gcode.py"


class CalibrationArtifactTests(unittest.TestCase):
    def run_script(self, script, *args):
        return subprocess.run([sys.executable, str(script), *map(str, args)], text=True, capture_output=True)

    def test_flow_is_review_only_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "flow.gcode.review"
            generated = self.run_script(GENERATOR, "--test", "flow", "--x-max", "250", "--y-max", "250", "--z-max", "250", "--output", artifact)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertIn("REVIEW-ONLY", artifact.read_text())
            validated = self.run_script(VALIDATOR, artifact, "--x-max", "250", "--y-max", "250", "--z-max", "250")
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_validator_rejects_heater_override(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "unsafe.gcode.review"
            artifact.write_text("; INDUS3D REVIEW-ONLY CALIBRATION TEST\n; Test: thermal\nM104 S280\n", encoding="utf-8")
            validated = self.run_script(VALIDATOR, artifact)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("prohibited command", validated.stdout)

    def test_generator_refuses_runnable_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.run_script(GENERATOR, "--test", "resonance", "--output", Path(directory) / "test.gcode")
            self.assertNotEqual(generated.returncode, 0)
            self.assertIn("never writes runnable G-code", generated.stderr)


if __name__ == "__main__":
    unittest.main()
