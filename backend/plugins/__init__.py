"""
plugins/__init__.py
--------------------
Plugin loader. Every ``plugins/<name>.py`` (not starting with ``_``) is a
plugin. A plugin may define any of:

    PLUGIN_INFO = {"title": str, "description": str}
    register_hooks(hooks)      # subscribe to the control-loop hooks
    register_routes(app)       # add Flask routes (use /api/v1/plugins/<name>/…)

See core/plugin_hooks.py for the hooks and docs/PLUGINS.md for the full
contract. Disable plugins with INDUS3D_DISABLED_PLUGINS=name1,name2.

A plugin that fails to import or register is logged and skipped; it can never
stop the backend from starting.
"""

import importlib
import logging
import os
from typing import Dict, List

from core.plugin_hooks import hooks

_loaded: Dict[str, dict] = {}
_routed: set = set()


def _disabled() -> set:
    return {n.strip() for n in os.environ.get("INDUS3D_DISABLED_PLUGINS", "").split(",") if n.strip()}


def loaded_plugins() -> List[dict]:
    return [dict(name=n, **info) for n, info in sorted(_loaded.items())]


def load_plugins(app=None) -> List[str]:
    """Discover and register plugins. Safe to call once at startup."""
    plugins_dir = os.path.dirname(__file__)
    disabled = _disabled()
    names: List[str] = []
    for filename in sorted(os.listdir(plugins_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        name = filename[:-3]
        if name in disabled:
            logging.info(f"🧩 Plugin disabled by INDUS3D_DISABLED_PLUGINS: {name}")
            continue
        try:
            module = importlib.import_module(f"plugins.{name}")
            if name not in _loaded:            # hooks are registered once per process
                if hasattr(module, "register_hooks"):
                    module.register_hooks(hooks)
                _loaded[name] = dict(getattr(module, "PLUGIN_INFO", {}) or {})
                names.append(name)
                logging.info(f"🧩 Plugin loaded: {name}")
            # routes are registered once per Flask app
            if app is not None and hasattr(module, "register_routes") and (name, id(app)) not in _routed:
                module.register_routes(app)
                _routed.add((name, id(app)))
        except Exception as e:  # noqa: BLE001
            logging.error(f"Failed to load plugin {name}: {e}")

    if app is not None and not any(r.endpoint == "plugins_index" for r in app.url_map.iter_rules()):
        from flask import jsonify

        @app.route("/api/v1/plugins", methods=["GET"], endpoint="plugins_index")
        def plugins_index():
            return jsonify({"plugins": loaded_plugins(), "disabled": sorted(disabled)})

    return names
