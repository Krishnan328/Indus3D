"""Telling one print job from the next when the printer state never visibly leaves "printing".

With Moonraker's job queue (and ``automatic_transition``) the next job is loaded within milliseconds of the
previous one completing, which is shorter than the telemetry poll interval. Every consumer that keys on the
``printing -> not printing -> printing`` transition (run recorder, spool planner, controller state, history,
timelapse, ...) would then see one endless print. ``is_new_job`` recognises the hand-over from two
consecutive "printing" snapshots so callers can synthesize the missing end/start.

A new job is either a different file, or the same file started again (queue "multiply"): Klipper's
``print_duration`` only ever grows within one job (pauses do not reset it), so a clear drop means a restart.
"""

from typing import Optional

PRINT_DURATION_DROP_S = 3.0


def job_ref(snap: dict) -> dict:
    """The part of a snapshot that identifies the running job."""
    try:
        dur = float(snap.get("print_duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"filename": snap.get("filename") or "", "print_duration": dur}


def is_new_job(prev: Optional[dict], snap: dict) -> bool:
    """True if ``snap`` (printing) belongs to a different job than ``prev`` (``job_ref`` of the last printing tick).

    An empty filename on either side is treated as "unknown", never as a change (Moonraker reports an empty
    name for a moment while it loads a file).
    """
    if not prev:
        return False
    cur = job_ref(snap)
    if prev["filename"] and cur["filename"] and prev["filename"] != cur["filename"]:
        return True
    return prev["print_duration"] - cur["print_duration"] > PRINT_DURATION_DROP_S


class JobEdges:
    """Per-tick start/end detection that also catches back-to-back jobs.

    ``step(snap)`` returns ``(ended, started, switched)``:

    * ``ended``    final state of the job that just ended ("complete", "cancelled", "error", ...) or None
    * ``started``  a job began on this tick
    * ``switched`` the hand-over happened without a visible gap: ``ended`` is then "complete" (a queue only
                   advances after a completed job) and ``started`` is True in the same tick, so the caller
                   must handle the end first, then the start.
    """

    def __init__(self):
        self.prev_state: Optional[str] = None
        self.ref: Optional[dict] = None

    def step(self, snap: dict):
        state = snap.get("print_state")
        printing = state in ("printing", "paused")
        was = self.prev_state in ("printing", "paused")
        switched = printing and was and is_new_job(self.ref, snap)
        ended = None
        if was and not printing:
            ended = state
        elif switched:
            ended = "complete"
        started = printing and (not was or switched)
        self.prev_state = state
        self.ref = job_ref(snap) if printing else None
        return ended, started, switched
