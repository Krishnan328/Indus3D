"""
core/plugin_hooks.py
---------------------
Tiny hook registry that lets plugins observe and adjust the control loop
without touching it.

Hooks (name -> callback signature)
  tick               fn(snap: dict, ctx: dict) -> None
        Every telemetry tick, printing or not.
  controller.inputs  fn(snap, kin, thm, ext, ctx) -> None
        Just before the quality controller runs; a plugin may add measured
        values to ``ext`` (mutate in place), e.g. a real extruder current.
  commands.filter    fn(commands: list[str], ctx: dict) -> list[str]
        Chain applied to the quality controller's output before anything is
        sent. Return the commands to keep; record why you dropped one with
        ``ctx_veto(ctx, command, plugin, reason)``.
  commands.sent      fn(results: list[dict], ctx: dict) -> None
        After sending. Each result: {"command", "ok", "ts"}.
  commands.vetoed    fn(vetoes: list[dict], ctx: dict) -> None
        Commands a filter dropped: {"command", "plugin", "reason"}.
  shadow.commands    fn(commands: list[str], ctx: dict) -> None
        Commands the controller *would* have sent while the auto-pilot is off.

Failure policy: a hook that raises is logged and skipped. A broken plugin can
never stop the control loop, and a failing filter leaves the commands
unchanged (the behaviour before plugins existed).
"""

import logging
import threading
from collections import defaultdict
from typing import Callable, Dict, List, Tuple

HOOK_NAMES = (
    "tick",
    "controller.inputs",
    "commands.filter",
    "commands.sent",
    "commands.vetoed",
    "shadow.commands",
)


class HookRegistry:
    def __init__(self):
        self._hooks: Dict[str, List[Tuple[int, int, Callable]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._seq = 0

    def on(self, name: str, fn: Callable, priority: int = 50) -> None:
        """Register ``fn`` for hook ``name``; lower priority numbers run first."""
        if name not in HOOK_NAMES:
            raise ValueError(f"unknown hook '{name}' (known: {', '.join(HOOK_NAMES)})")
        with self._lock:
            self._seq += 1
            self._hooks[name].append((priority, self._seq, fn))
            self._hooks[name].sort(key=lambda t: (t[0], t[1]))

    def clear(self) -> None:
        with self._lock:
            self._hooks.clear()

    def _callbacks(self, name: str) -> List[Callable]:
        with self._lock:
            return [fn for _, _, fn in self._hooks.get(name, [])]

    def emit(self, name: str, *args) -> None:
        for fn in self._callbacks(name):
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001 — plugins must not break the loop
                logging.error(f"🧩 hook '{name}' failed in {getattr(fn, '__module__', fn)}: {e}")

    def apply(self, name: str, value: list, *args) -> list:
        """Run a filter chain. A callback that raises or returns a non-list is ignored."""
        for fn in self._callbacks(name):
            try:
                out = fn(list(value), *args)
                if isinstance(out, list):
                    value = out
            except Exception as e:  # noqa: BLE001
                logging.error(f"🧩 filter '{name}' failed in {getattr(fn, '__module__', fn)}: {e}")
        return value


hooks = HookRegistry()


def ctx_veto(ctx: dict, command: str, plugin: str, reason: str) -> None:
    """Record that ``plugin`` dropped ``command`` (surfaced to audit/UI plugins)."""
    ctx.setdefault("vetoes", []).append({"command": command, "plugin": plugin, "reason": reason})
