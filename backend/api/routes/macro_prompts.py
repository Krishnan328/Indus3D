"""
api/routes/macro_prompts.py
----------------------------
Klipper action:prompt_* protocol handler.

Klipper macros can display interactive dialogs by writing lines like:
  action:prompt_begin Confirm filament load?
  action:prompt_text Is the filament fully loaded and purged?
  action:prompt_button Confirm|LOAD_FILAMENT_CONFIRM
  action:prompt_button Cancel|RESPOND TYPE=error MSG='Cancelled'
  action:prompt_footer_button Emergency Stop!|EMERGENCY_STOP|error
  action:prompt_show

These arrive via the Moonraker notify_gcode_response feed as console lines.

Endpoints (all under /api/v1/printer/prompt, registered in server.py):
  GET  /api/v1/printer/prompt           → current prompt state
  POST /api/v1/printer/prompt/respond   → click a button (requires auth)
  DELETE /api/v1/printer/prompt         → dismiss the prompt (requires auth)
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from flask import Blueprint, jsonify, request

from api import moonraker_util
from api.auth import auth_required, _is_authenticated

prompt_bp = Blueprint("prompt", __name__)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PromptState:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    text: List[str] = field(default_factory=list)
    buttons: List[Dict] = field(default_factory=list)
    footer_buttons: List[Dict] = field(default_factory=list)
    active: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "text": list(self.text),
            "buttons": [dict(button) for button in self.buttons],
            "footer_buttons": [dict(button) for button in self.footer_buttons],
            "active": self.active,
        }


# ── Parser ────────────────────────────────────────────────────────────────────

_BUTTON_STYLES = {"warning", "error"}


def parse_prompt_line(line: str) -> Optional[dict]:
    """Parse a single console output line for action:prompt_* directives.

    Returns a dict with 'type' and 'payload', or None if the line is not a
    prompt directive.
    """
    if not isinstance(line, str):
        return None

    # Strip leading/trailing whitespace and common prefixes from notify_gcode_response
    stripped = line.strip()
    if stripped.startswith("//"):
        stripped = stripped[2:].lstrip()

    # Handle the case where the line object may carry a 'text' key (from liveCommands)
    # Callers should pass the raw text string.

    if not stripped.startswith("action:prompt_"):
        return None

    # Strip the action:prompt_ prefix
    rest = stripped[len("action:prompt_"):]

    if rest.startswith("begin "):
        return {"type": "begin", "payload": rest[6:].strip()}

    if rest.startswith("text "):
        return {"type": "text", "payload": rest[5:].strip()}

    if rest.startswith("button "):
        raw = rest[7:].strip()
        parts = raw.split("|")
        label = parts[0].strip() if len(parts) > 0 else ""
        command = parts[1].strip() if len(parts) > 1 else ""
        style_raw = parts[2].strip().lower() if len(parts) > 2 else "normal"
        style = style_raw if style_raw in _BUTTON_STYLES else "normal"
        return {"type": "button", "payload": {"label": label, "command": command, "style": style}}

    if rest.startswith("footer_button "):
        raw = rest[14:].strip()
        parts = raw.split("|")
        label = parts[0].strip() if len(parts) > 0 else ""
        command = parts[1].strip() if len(parts) > 1 else ""
        style_raw = parts[2].strip().lower() if len(parts) > 2 else "normal"
        style = style_raw if style_raw in _BUTTON_STYLES else "normal"
        return {"type": "footer_button", "payload": {"label": label, "command": command, "style": style}}

    if rest == "show":
        return {"type": "show", "payload": None}

    if rest == "end":
        return {"type": "end", "payload": None}

    return None


# ── Manager (singleton) ───────────────────────────────────────────────────────

class MacroPromptManager:
    """Thread-safe singleton that tracks the current action:prompt_* state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Optional[PromptState] = None   # being built (after begin, before show)
        self._active: Optional[PromptState] = None    # shown to user

    def feed(self, line: str) -> None:
        """Call with every console/gcode-response line."""
        # Accept both raw strings and dict objects with a 'text' key
        if isinstance(line, dict):
            line = line.get("text", "")

        parsed = parse_prompt_line(line)
        if parsed is None:
            return

        ptype = parsed["type"]
        payload = parsed["payload"]

        with self._lock:
            if ptype == "begin":
                self._pending = PromptState(title=payload, active=False)

            elif ptype == "text":
                if self._pending is not None:
                    self._pending.text.append(payload)

            elif ptype == "button":
                if self._pending is not None:
                    self._pending.buttons.append(payload)

            elif ptype == "footer_button":
                if self._pending is not None:
                    self._pending.footer_buttons.append(payload)

            elif ptype == "show":
                if self._pending is not None:
                    self._pending.active = True
                    self._active = self._pending
                    self._pending = None

            elif ptype == "end":
                self._pending = None
                self._active = None

    def get_state(self) -> Optional[dict]:
        """Return current prompt dict or None if no active prompt."""
        with self._lock:
            if self._active is None:
                return None
            return self._active.to_dict()

    def close(self) -> None:
        """Clear the prompt (called on prompt_end or user button click)."""
        with self._lock:
            self._pending = None
            self._active = None

    def get_valid_commands(self) -> List[str]:
        """Return all valid button commands from the current active prompt."""
        with self._lock:
            if self._active is None:
                return []
            cmds = [b["command"] for b in self._active.buttons]
            cmds += [b["command"] for b in self._active.footer_buttons]
            return cmds

    def claim(self, command, prompt_id=None):
        with self._lock:
            prompt = self._active
            if prompt is None:
                return None, "No active prompt", 404
            if prompt_id is not None and prompt_id != prompt.id:
                return None, "The printer prompt changed; review the current dialog", 409
            valid = [button["command"] for button in prompt.buttons + prompt.footer_buttons]
            if command not in valid:
                return None, "Unknown command for the active prompt", 400
            self._active = None
            return prompt, None, 200

    def restore(self, prompt):
        with self._lock:
            if self._active is None and self._pending is None:
                self._active = prompt


# Module-level singleton instance
macro_prompt_manager = MacroPromptManager()


# ── Flask routes ──────────────────────────────────────────────────────────────

@prompt_bp.route("", methods=["GET"])
def get_prompt():
    """Return the current action:prompt_* dialog state.

    Response: {"active": bool, "prompt": {...} | null}
    """
    state = macro_prompt_manager.get_state()
    return jsonify({
        "active": state is not None,
        "prompt": state,
    })


@prompt_bp.route("/respond", methods=["POST"])
def respond_to_prompt():
    """Execute a prompt button command.

    Body: {"command": "LOAD_FILAMENT_CONFIRM"}
    Requires: auth cookie (when auth is enabled).
    """
    if auth_required():
        if not _is_authenticated():
            return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict) or not isinstance(data.get("command"), str):
        return jsonify({"error": "command must be a string"}), 400
    command = data["command"].strip()
    import workers
    if workers.is_simulator(workers._active_worker):
        return jsonify({"error": "Live printer prompts are unavailable in simulation mode"}), 409
    if not command:
        return jsonify({"error": "command is required"}), 400

    prompt, error, status = macro_prompt_manager.claim(command, data.get("prompt_id"))
    if error:
        return jsonify({"error": error}), status

    try:
        moonraker_util.run_script_checked(command)
    except moonraker_util.ScriptRejected as e:
        macro_prompt_manager.restore(prompt)
        return jsonify({"error": str(e)}), 422
    except moonraker_util.MoonrakerError as e:
        logging.warning("MacroPromptManager: Moonraker error running %s: %s", command, e)
        macro_prompt_manager.restore(prompt)
        return jsonify({"error": str(e)}), 502

    return jsonify({"status": "ok", "command": command})


@prompt_bp.route("", methods=["DELETE"])
def dismiss_prompt():
    """Force-close (dismiss) the active prompt without running any command.

    Requires: auth cookie (when auth is enabled).
    """
    if auth_required():
        if not _is_authenticated():
            return jsonify({"error": "Authentication required"}), 401

    macro_prompt_manager.close()
    return jsonify({"status": "ok"})
