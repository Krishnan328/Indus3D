# Indus3D KIAUH extension — shared constants.
#
# Everything a maintainer is likely to change lives here; the extension module
# itself holds only the install / update / remove logic.

from pathlib import Path

INDUS_REPO = "https://github.com/Krishnan328/Indus3D.git"
# `main` currently holds the initial public release. Point this at "main" once
# the v2.0 work has been merged there.
INDUS_BRANCH = "v2.0-staging"

INDUS_DIR = Path.home().joinpath("Indus3D")
INDUS_BACKEND_DIR = INDUS_DIR.joinpath("backend")
INDUS_ENV = INDUS_BACKEND_DIR.joinpath(".venv")
INDUS_REQ_FILE = INDUS_BACKEND_DIR.joinpath("requirements.txt")
INDUS_FRONTEND_DIR = INDUS_DIR.joinpath("frontend")
INDUS_CFG_SRC = INDUS_DIR.joinpath("indus3d.cfg")
INDUS_KLIPPER_MODULE_SRC = INDUS_DIR.joinpath("klipper_modules/indus_vibration.py")

INDUS_SERVICE = "indus3d.service"
INDUS_TRACKER_SERVICE = "indus3d-tracker.service"
INDUS_TRACKER_SCRIPT = INDUS_DIR.joinpath("helpers/trackers/corrective_gcode_tracker.py")
INDUS_SENSOR_INSTALLER = INDUS_DIR.joinpath("helpers/filament_sensor/install_sensor.py")
INDUS_SENSOR_SERVICE = "indus3d-filament-sensor.service"
INDUS_CFG_NAME = "indus3d.cfg"
INDUS_PORT = 5001

KLIPPER_DIR = Path.home().joinpath("klipper")
KLIPPER_EXTRAS = KLIPPER_DIR.joinpath("klippy/extras")
KLIPPER_MODULE_NAME = "indus_vibration.py"

# System packages Indus3D needs on Debian-family hosts (KIAUH installs the
# missing ones itself).
INDUS_DEPS = {"python3-venv", "python3-pip", "ffmpeg", "curl", "git"}
