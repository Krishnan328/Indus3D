"""
services/quality_metrics.py
----------------------------
Quality figures that are actually measured (rows in ``action_log``), shared by the QA report and the
completion notification. Kept free of heavy imports (the QA reporter pulls in matplotlib).
"""
import logging
from typing import List, Optional, Tuple

# alert ids that count as an out-of-spec excursion on the AS9100 certificate
EXCURSION_ALERT_IDS = ("temp_runaway", "bed_runaway", "vibration_high")


def count_excursions(start_ts: float, end_ts: float) -> Optional[int]:
    """Logged excursions in [start_ts, end_ts]; None when it cannot be determined (no timestamps or DB error),
    so callers never present an unmeasured value as "0"."""
    if not start_ts or not end_ts:
        return None
    try:
        from db.models import get_connection
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT alert_id FROM action_log WHERE timestamp >= ? AND timestamp <= ?", (start_ts, end_ts)
            ).fetchall()
        finally:
            conn.close()
        return sum(1 for r in rows if r[0] in EXCURSION_ALERT_IDS)
    except Exception as e:  # noqa: BLE001
        logging.info(f"Excursion count unavailable: {e}")
        return None
