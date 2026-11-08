"""
db/migrator.py
-----------------
Lightweight SQLite migration runner for Indus3D.

How it works:
  1. Maintains a `schema_version` table with a single row tracking the
     current version number.
  2. On startup, scans `db/migrations/` for numbered Python files
     (e.g., `001_add_disk_columns.py`).
  3. Runs any migration whose number is greater than the current version,
     in order.
  4. Each migration file must have a `def up(conn):` function that receives
     a sqlite3 connection and performs the schema change.
  5. After all pending migrations succeed, the schema version is updated.

Design choices:
  - No `down()` / rollback — for a single-user 3D printer dashboard, this
    adds complexity without real value. If a migration breaks something,
    the fix is a new forward migration.
  - Migrations run inside a transaction (sqlite3's implicit one). If a
    migration fails, it rolls back and the process exits with an error
    rather than running with a half-migrated schema.
  - The migrations directory is scanned by filename prefix (NNN_), not by
    a separate registry — simple, deterministic, git-friendly.
"""

import logging
import importlib.util
import os
import sys
from db.models import get_connection

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def _ensure_version_table(conn):
    """Create the schema_version table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            id      INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)
    """)
    conn.commit()


def _get_version(conn) -> int:
    """Return the current schema version."""
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return row[0] if row else 0


def _set_version(conn, version: int):
    """Update the schema version."""
    conn.execute("UPDATE schema_version SET version = ? WHERE id = 1", (version,))
    conn.commit()


def _discover_migrations() -> list:
    """Scan the migrations directory for numbered Python files.
    Returns a sorted list of (version_number, filepath, module_name) tuples."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []

    migrations = []
    for fname in sorted(os.listdir(MIGRATIONS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        # Extract version number from prefix: "001_description.py" → 1
        prefix = fname.split("_", 1)[0]
        try:
            version = int(prefix)
        except ValueError:
            continue
        migrations.append((version, os.path.join(MIGRATIONS_DIR, fname), fname))

    return migrations


def _load_migration(filepath: str, name: str):
    """Dynamically import a migration module."""
    spec = importlib.util.spec_from_file_location(f"migration_{name}", filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_migrations():
    """Run all pending migrations. Called from main.py on startup,
    after init_db() creates the base tables.

    If any migration fails, the process exits with an error — running
    with a half-migrated schema is worse than not starting."""
    conn = get_connection()
    _ensure_version_table(conn)
    current = _get_version(conn)

    migrations = _discover_migrations()
    pending = [(v, fp, name) for v, fp, name in migrations if v > current]

    if not pending:
        return

    logging.info(f"📦 Running {len(pending)} database migration(s) (current version: {current})...")

    for version, filepath, name in pending:
        try:
            mod = _load_migration(filepath, name)
            if not hasattr(mod, "up"):
                logging.info(f"   ⚠️  {name}: no up() function, skipping")
                continue
            mod.up(conn)
            _set_version(conn, version)
            logging.info(f"   ✅ {name} → version {version}")
        except Exception as e:
            logging.info(f"   🔴 Migration {name} failed: {e}")
            logging.info(f"   Database is at version {_get_version(conn)}. Fix the migration and restart.")
            conn.close()
            sys.exit(1)

    conn.close()
    logging.info(f"📦 Migrations complete (now at version {_get_version(get_connection())})")
