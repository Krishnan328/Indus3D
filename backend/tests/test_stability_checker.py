import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from check_system_stability import StabilityChecker


def test_stability_checker_host_vitals():
    checker = StabilityChecker()
    checker.check_host_vitals()
    assert "Host Vitals" in checker.results["checks"]
    vitals = checker.results["checks"]["Host Vitals"]
    assert len(vitals) >= 2


def test_stability_checker_summary_output(capsys):
    checker = StabilityChecker()
    checker.check_host_vitals()
    checker.print_summary()
    captured = capsys.readouterr()
    assert "INDUS3D SYSTEM STABILITY & HARDWARE AUDIT" in captured.out
    assert "Host Vitals" in captured.out
