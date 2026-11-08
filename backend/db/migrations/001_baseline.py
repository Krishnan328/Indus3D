"""
Migration 001: Baseline
--------------------------
This migration doesn't change anything — it simply establishes version 1 as
the baseline for the existing schema created by init_db() in models.py:

  - command_log
  - odometry
  - print_history
  - twin_snapshots
  - action_log

All future schema changes go in 002+. Having a baseline lets the migrator
know "this database has been through the migration system" vs "this is an
old database that predates migrations."
"""


def up(conn):
    # Nothing to do — init_db() already created all tables.
    # This migration just moves the version counter to 1.
    pass
