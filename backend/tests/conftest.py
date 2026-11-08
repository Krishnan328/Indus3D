import pytest
import sys
import os

# Add backend directory to sys.path so we can import from core, digital_twin, etc.
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from db.models import init_db
init_db()
