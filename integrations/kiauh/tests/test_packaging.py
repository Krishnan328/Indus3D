"""Packaging regression tests; all writes and mocked installs stay in temp dirs."""

from abc import ABC, abstractmethod
import ast
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
KIAUH = ROOT / "integrations" / "kiauh"
INSTALLER = KIAUH / "indus3d_installer.sh"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config_file = load_module("indus3d_config_file", KIAUH / "config_file.py")


class ConfigRemovalTests(unittest.TestCase):
    def test_adjacent_sections_and_backup_are_preserved(self):
        original = "[server]\nport: 7125\n[update_manager indus3d]\ntype: git_repo\npath: /tmp/project\n[update_manager other]\ntype: git_repo\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moonraker.conf"
            path.write_text(original)
            path.chmod(0o640)
            backup = config_file.remove_entry(path, "update_manager indus3d")
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(path.read_text(), "[server]\nport: 7125\n[update_manager other]\ntype: git_repo\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertIsNone(config_file.remove_entry(path, "update_manager indus3d"))

    def test_include_removes_only_exact_line(self):
        original = "[include indus3d.cfg] # integration\n# retain my comment\n[include other.cfg]\n[printer]\nkinematics: cartesian\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "printer.cfg"
            path.write_text(original)
            config_file.remove_entry(path, "include indus3d.cfg")
            self.assertEqual(path.read_text(), original.split("\n", 1)[1])

    def test_last_section_and_whitespace_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moonraker.conf"
            path.write_text("[server]\nport: 7125\n  [update_manager indus3d] # local\ntype: git_repo\n")
            config_file.remove_entry(path, "update_manager indus3d")
            self.assertEqual(path.read_text(), "[server]\nport: 7125\n")


class ExtensionTests(unittest.TestCase):
    def test_actual_upstream_discovery(self):
        upstream = os.environ.get("KIAUH_SOURCE_DIR")
        if not upstream:
            self.skipTest("Set KIAUH_SOURCE_DIR to test the actual upstream loader")
        source = Path(upstream) / "kiauh/extensions/extensions_menu.py"
        tree = ast.parse(source.read_text())
        method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                      for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "discover_extensions")
        base_module = load_module("extensions.base_extension", Path(upstream) / "kiauh/extensions/base_extension.py")
        extension = None
        with patch.dict(sys.modules, {"extensions.base_extension": base_module}):
            extension = load_module("indus3d_extension", KIAUH / "extension.py")
        warnings = []
        importer = types.SimpleNamespace(import_module=lambda name: extension)
        logger = types.SimpleNamespace(print_warn=warnings.append)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "indus3d"
            folder.mkdir()
            (folder / "metadata.json").write_bytes((KIAUH / "metadata.json").read_bytes())
            namespace = {"EXTENSION_ROOT": Path(directory), "Path": Path, "json": json,
                         "Dict": dict, "BaseExtension": base_module.BaseExtension,
                         "inspect": inspect, "importlib": importer, "Logger": logger,
                         "GITHUB_ISSUES_URL": "https://github.com/dw-0/kiauh/issues"}
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
            found = namespace["discover_extensions"](None)
            self.assertEqual(list(found), ["99"], warnings)
            self.assertEqual(found["99"].metadata["module"], "extension")
            self.assertEqual(warnings, [])

    def test_upstream_extension_contract(self):
        # Use the real upstream ABC when available; CI uses the same public contract.
        upstream = os.environ.get("KIAUH_SOURCE_DIR")
        if upstream:
            base_module = load_module("extensions.base_extension", Path(upstream) / "kiauh/extensions/base_extension.py")
        else:
            class BaseExtension(ABC):
                def __init__(self, metadata):
                    self.metadata = metadata

                @abstractmethod
                def install_extension(self, **kwargs):
                    pass

                @abstractmethod
                def remove_extension(self, **kwargs):
                    pass

            base_module = types.ModuleType("extensions.base_extension")
            base_module.BaseExtension = BaseExtension
        with patch.dict(sys.modules, {"extensions.base_extension": base_module}):
            extension = load_module("indus3d_extension", KIAUH / "extension.py")
            metadata = json.loads((KIAUH / "metadata.json").read_text())["metadata"]
            self.assertIsInstance(metadata["index"], int)
            self.assertEqual(metadata["module"], "extension")
            classes = inspect.getmembers(extension, lambda item: inspect.isclass(item) and issubclass(item, base_module.BaseExtension) and item != base_module.BaseExtension)
            self.assertEqual(len(classes), 1)
            instance = classes[0][1](metadata)
            self.assertEqual(instance.metadata["display_name"], "Indus3D Digital Twin")
            with patch.object(extension.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                instance.install_extension()
                instance.update_extension()
                instance.remove_extension()
                self.assertEqual([call.args[0][-1] for call in run.call_args_list], ["install", "update", "remove"])
            with patch.object(extension.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaises(RuntimeError):
                    instance.install_extension()

    def test_registration_uses_real_extension_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "kiauh"
            (checkout / "kiauh/extensions").mkdir(parents=True)
            (checkout / "kiauh.sh").touch()
            subprocess.run(["bash", str(KIAUH / "install-extension.sh"), str(checkout)], check=True, capture_output=True)
            destination = checkout / "kiauh/extensions/indus3d"
            for name in ("metadata.json", "extension.py", "indus3d_installer.sh", "config_file.py"):
                self.assertEqual((destination / name).read_bytes(), (KIAUH / name).read_bytes())
            self.assertFalse((checkout / "extensions").exists())


class InstallerTests(unittest.TestCase):
    def shell(self, script, *arguments, env=None):
        return subprocess.run(["bash", "-euc", 'source "$1"; shift; run_as_user() { "$@"; }; ' + script, "_", str(INSTALLER), *map(str, arguments)], text=True, capture_output=True, env=env)

    def git(self, *arguments):
        return subprocess.run(["git", *map(str, arguments)], check=True, text=True, capture_output=True)

    def create_repositories(self, directory):
        remote, author, installed = [Path(directory) / name for name in ("remote.git", "author", "installed")]
        self.git("init", "--bare", remote)
        self.git("init", author)
        self.git("-C", author, "config", "user.name", "Packaging Test")
        self.git("-C", author, "config", "user.email", "packaging@example.invalid")
        (author / "overrides.cfg").write_text("offset=0.1\n")
        self.git("-C", author, "add", ".")
        self.git("-C", author, "commit", "-m", "initial")
        self.git("-C", author, "branch", "-M", "main")
        self.git("-C", author, "remote", "add", "origin", remote)
        self.git("-C", author, "push", "-u", "origin", "main")
        self.git("clone", "--branch", "main", remote, installed)
        return author, installed

    def test_dirty_configuration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            _, installed = self.create_repositories(directory)
            config = installed / "overrides.cfg"
            config.write_text("offset=0.25\n")
            result = self.shell('INSTALL_DIR="$1"; REPO_BRANCH=main; update_codebase', installed)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("local changes", result.stderr)
            self.assertEqual(config.read_text(), "offset=0.25\n")

    def test_clean_update_fast_forwards(self):
        with tempfile.TemporaryDirectory() as directory:
            author, installed = self.create_repositories(directory)
            (author / "feature.txt").write_text("new feature\n")
            self.git("-C", author, "add", ".")
            self.git("-C", author, "commit", "-m", "feature")
            self.git("-C", author, "push")
            result = self.shell('INSTALL_DIR="$1"; REPO_BRANCH=main; update_codebase', installed)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((installed / "feature.txt").read_text(), "new feature\n")

    def test_diverged_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            author, installed = self.create_repositories(directory)
            self.git("-C", installed, "config", "user.name", "Packaging Test")
            self.git("-C", installed, "config", "user.email", "packaging@example.invalid")
            for checkout, name in ((author, "remote.txt"), (installed, "local.txt")):
                (checkout / name).write_text(name)
                self.git("-C", checkout, "add", ".")
                self.git("-C", checkout, "commit", "-m", name)
            self.git("-C", author, "push")
            before = self.git("-C", installed, "rev-parse", "HEAD").stdout
            result = self.shell('INSTALL_DIR="$1"; REPO_BRANCH=main; update_codebase', installed)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.git("-C", installed, "rev-parse", "HEAD").stdout, before)
            self.assertTrue((installed / "local.txt").exists())

    def test_install_builds_assets_before_starting_service(self):
        result = self.shell('''
            for name in install_system_deps setup_codebase setup_python_env build_frontend build_rust_dsp setup_systemd_service configure_moonraker_update_manager configure_klipper_macros; do
                eval "$name() { echo CALL:$name; }"
            done
            TARGET_USER=tester
            do_install
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [line for line in result.stdout.splitlines() if line.startswith("CALL:")]
        self.assertLess(calls.index("CALL:build_frontend"), calls.index("CALL:setup_systemd_service"))
        self.assertLess(calls.index("CALL:build_rust_dsp"), calls.index("CALL:setup_systemd_service"))

    def test_failed_frontend_install_stops_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend").mkdir()
            binary = root / "bin"
            binary.mkdir()
            (binary / "node").write_text("#!/bin/sh\nexit 0\n")
            (binary / "npm").write_text('#!/bin/sh\nif [ "$1" = ci ]; then exit 17; fi\ntouch build-was-run\n')
            for path in binary.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}")
            result = self.shell('INSTALL_DIR="$1"; build_frontend', root, env=env)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertFalse((root / "frontend/build-was-run").exists())

    def test_missing_cargo_fails_instead_of_claiming_fallback(self):
        result = self.shell('''
            command() { if [ "$1" = -v ] && [ "$2" = cargo ]; then return 1; fi; builtin command "$@"; }
            build_rust_dsp
        ''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no Python fallback", result.stdout)

    def test_update_rebuilds_both_assets_before_restart(self):
        result = self.shell('''
            update_codebase() { echo CALL:update; }
            setup_python_env() { echo CALL:python; }
            build_frontend() { echo CALL:frontend; }
            build_rust_dsp() { echo CALL:dsp; }
            sudo() { echo CALL:restart; }
            do_update
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("CALL:")],
                         ["CALL:update", "CALL:python", "CALL:frontend", "CALL:dsp", "CALL:restart"])

    def test_failed_build_never_restarts_service(self):
        result = self.shell('''
            update_codebase() { :; }
            setup_python_env() { :; }
            build_frontend() { return 19; }
            build_rust_dsp() { echo UNEXPECTED_DSP; }
            sudo() { echo UNEXPECTED_RESTART; }
            do_update
        ''')
        self.assertEqual(result.returncode, 19)
        self.assertNotIn("UNEXPECTED", result.stdout)

    def test_frontend_build_creates_required_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend").mkdir()
            binary = root / "bin"
            binary.mkdir()
            (binary / "node").write_text("#!/bin/sh\nexit 0\n")
            (binary / "npm").write_text('#!/bin/sh\necho "$*" >> npm-calls\nif [ "$1" = run ]; then mkdir -p dist; echo dashboard > dist/index.html; fi\n')
            for path in binary.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}")
            result = self.shell('INSTALL_DIR="$1"; build_frontend', root, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "frontend/npm-calls").read_text().splitlines(), ["ci --include=dev", "run build"])
            self.assertTrue((root / "frontend/dist/index.html").is_file())


if __name__ == "__main__":
    unittest.main()
