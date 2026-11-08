import os
import importlib
import logging

def load_plugins(app):
    plugins_dir = os.path.dirname(__file__)
    for filename in os.listdir(plugins_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                module = importlib.import_module(f"plugins.{module_name}")
                if hasattr(module, "register_routes"):
                    module.register_routes(app)
                logging.info(f"🧩 Plugin loaded: {module_name}")
            except Exception as e:
                logging.error(f"Failed to load plugin {module_name}: {e}")
