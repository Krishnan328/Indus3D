"""
Unit tests for bed_safety.py
"""

import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from digital_twin.bed_safety import BedSafetyEngine


def test_orca_profile_parsing():
    engine = BedSafetyEngine()

    sample_orca = {
        "type": "machine",
        "name": "Ender 3 S1 Pro",
        "printable_area": [
            "0x0",
            "220x0",
            "220x220",
            "0x220"
        ],
        "printable_height": "270",
        "bed_exclude_area": [
            "0x0",
            "30x0",
            "30x30",
            "0x30"
        ]
    }

    result = engine.parse_orca_profile(sample_orca, "Test Ender")
    assert result["size_x_mm"] == 220.0
    assert result["size_y_mm"] == 220.0
    assert result["size_z_mm"] == 270.0
    assert result["origin_center"] is False
    assert len(result["printable_area"]) == 4
    assert len(result["bed_exclude_area"]) == 1
    assert result["bed_exclude_area"][0] == [[0.0, 0.0], [30.0, 0.0], [30.0, 30.0], [0.0, 30.0]]
    print("✅ test_orca_profile_parsing passed")


def test_collision_detection():
    engine = BedSafetyEngine()
    engine.min_x, engine.max_x = 0.0, 220.0
    engine.min_y, engine.max_y = 0.0, 220.0
    engine.printable_area = [[0, 0], [220, 0], [220, 220], [0, 220]]
    engine.bed_exclude_area = [
        [[10, 10], [30, 10], [30, 30], [10, 30]] # Corner screw at X=20, Y=20
    ]
    engine.clearance_height_mm = 10.0

    # Inside screw zone at Z=1mm -> dangerous!
    in_zone, idx = engine.is_in_exclusion_zone(20.0, 20.0, z=1.0)
    assert in_zone is True
    assert idx == 0

    # Inside screw zone but at Z=15mm -> safe overfly!
    in_zone_high, _ = engine.is_in_exclusion_zone(20.0, 20.0, z=15.0)
    assert in_zone_high is False

    # Outside screw zone at Z=1mm -> safe
    in_zone_out, _ = engine.is_in_exclusion_zone(100.0, 100.0, z=1.0)
    assert in_zone_out is False

    # Validate move through screw zone at Z=2mm
    safe, reason = engine.validate_move(5.0, 20.0, 2.0, 50.0, 20.0, 2.0)
    assert safe is False
    assert "crosses bed screw/exclusion zone" in reason

    # Validate move over screw zone at Z=12mm
    safe_high, _ = engine.validate_move(5.0, 20.0, 12.0, 50.0, 20.0, 12.0)
    assert safe_high is True
    print("✅ test_collision_detection passed")


def test_z_offset_clamping():
    engine = BedSafetyEngine()
    engine.bed_exclude_area = [
        [[10, 10], [30, 10], [30, 30], [10, 30]] # Screw at X=20, Y=20
    ]
    engine.clearance_height_mm = 10.0

    # Normal adjustment in open bed space
    adj = engine.clamp_z_offset(0.0, -0.05, x=100.0, y=100.0)
    assert adj == -0.05

    # Runaway negative offset clamped to -0.25 max
    adj_runaway = engine.clamp_z_offset(-0.20, -0.10, x=100.0, y=100.0)
    assert adj_runaway == -0.05 # clamped so -0.20 + (-0.05) = -0.25

    # Over screw zone: NO negative adjustments allowed!
    adj_screw = engine.clamp_z_offset(0.0, -0.05, x=20.0, y=20.0)
    assert adj_screw == 0.0

    # Over screw zone: positive (upward) adjustment allowed
    adj_screw_up = engine.clamp_z_offset(0.0, +0.05, x=20.0, y=20.0)
    assert adj_screw_up == +0.05
    print("✅ test_z_offset_clamping passed")


if __name__ == "__main__":
    test_orca_profile_parsing()
    test_collision_detection()
    test_z_offset_clamping()
    print("🎉 All Bed Safety unit tests passed successfully!")
