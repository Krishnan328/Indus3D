"""
core/command_pipeline.py
-------------------------
The single path every quality-controller command takes to the printer:

    controller.update()  ->  shadow hooks  ->  commands.filter chain
                         ->  send          ->  commands.sent / commands.vetoed

Both the live telemetry worker and the simulator call ``run_quality_cycle`` so
plugins (audit trail, arbiter, watchdog, shadow mode) behave identically in
simulation and on a real printer. With no plugins registered this is exactly
the previous behaviour: update, then send each command.
"""

import logging
import time
from typing import Callable, List, Optional

from core.plugin_hooks import hooks


def _ok(sent) -> bool:
    # send callbacks either return a bool (Moonraker) or None (simulator inject)
    return True if sent is None else bool(sent)


def tick(snap: dict, source: str = "live") -> None:
    """Notify plugins of a fresh telemetry snapshot (printing or not)."""
    hooks.emit("tick", snap, {"source": source, "now": time.time()})


def run_quality_cycle(controller, snap: dict, kin: dict, thm: dict, ext: dict,
                      send: Callable[[str], Optional[bool]], source: str = "live",
                      autoz: Optional[dict] = None) -> List[dict]:
    """Run one controller update and dispatch its commands.

    Returns one result dict per command actually sent.
    """
    now = time.time()
    hooks.emit("controller.inputs", snap, kin, thm, ext,
               {"source": source, "now": now, "autopilot": bool(controller.auto_pilot)})
    commands = controller.update(snap, kin, thm, ext, autoz) if autoz is not None \
        else controller.update(snap, kin, thm, ext)

    ctx = {
        "source": source,
        "send": send,        # lets a plugin release a held command later (approval mode)
        "now": now,
        "snap": snap,
        "autopilot": bool(controller.auto_pilot),
        "controller": controller,
        "corrections": list(getattr(controller, "last_corrections", []) or []),
        "vetoes": [],
    }

    shadow = getattr(controller, "last_shadow", None)
    if shadow and (shadow.get("commands") or shadow.get("corrections")):
        sctx = dict(ctx, corrections=list(shadow.get("corrections") or []))
        hooks.emit("shadow.commands", list(shadow.get("commands") or []), sctx)

    return dispatch_commands(commands, ctx)


def dispatch_commands(commands: List[str], ctx: dict) -> List[dict]:
    """Dispatch automatic and approved commands through the same current safeguards."""
    send = ctx["send"]
    controller = ctx.get("controller")
    kept = hooks.apply("commands.filter", list(commands), ctx)

    results: List[dict] = []
    for cmd in kept:
        try:
            ok = _ok(send(cmd))
        except Exception as e:  # noqa: BLE001 — a send failure is data, not a crash
            logging.error(f"⚠️  send failed for {cmd!r}: {e}")
            ok = False
        results.append({"command": cmd, "ok": ok, "ts": time.time()})

    if ctx["vetoes"]:
        # A dropped command must not stay "applied" in the controller's mind.
        forget = getattr(controller, "notify_vetoed", None)
        for v in ctx["vetoes"]:
            if forget:
                try:
                    forget(v["command"])
                except Exception as e:  # noqa: BLE001
                    logging.error(f"notify_vetoed failed for {v['command']!r}: {e}")
        hooks.emit("commands.vetoed", ctx["vetoes"], ctx)
    if results or ctx["corrections"]:
        hooks.emit("commands.sent", results, ctx)
    return results
