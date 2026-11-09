"""Exercise the installed scanner without real credentials or network calls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    scanner = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if not scanner:
        raise SystemExit("Install Gitleaks v8.24.2 before running scanner controls.")
    command = [scanner, "stdin", "--redact", "--no-banner", "--config", str(ROOT / ".gitleaks.toml")]
    samples = [
        ("ordinary text", "nothing confidential here", 0),
        ("synthetic Telegram token", "bot_token=" + "123456789" + ":" + "A" * 35, 1),
        ("synthetic GitHub token", "access_token=" + "ghp_" + "AbCdEf0123456789" * 2 + "XyZ9", 1),
    ]
    for label, sample, expected in samples:
        result = subprocess.run(command, input=sample, text=True, capture_output=True)
        if result.returncode != expected:
            raise SystemExit(f"Scanner control failed: {label} (exit {result.returncode}, expected {expected})")
    with tempfile.TemporaryDirectory(prefix="indus3d-scanner-control-") as folder:
        cwd = Path(folder)
        subprocess.run(["git", "init", "-q", folder], check=True)
        path = cwd / "frontend/src/files/prefs.js"
        path.parent.mkdir(parents=True)
        path.write_text('const KEY = "' + "indus3d_" + 'fm_prefs_v1";\n', encoding="utf-8")
        subprocess.run(["git", "-C", folder, "add", "."], check=True)
        staged = [scanner, "git", "--pre-commit", "--staged", "--redact", "--no-banner",
                  "--config", str(ROOT / ".gitleaks.toml")]
        result = subprocess.run(staged, cwd=folder, capture_output=True)
        if result.returncode != 0:
            raise SystemExit("The exact preference-name allowlist failed.")
        # A credential added to the same file must not inherit the line's exemption.
        with path.open("a", encoding="utf-8") as fh:
            fh.write("bot_token=" + "123456789" + ":" + "B" * 35 + "\n")
        subprocess.run(["git", "-C", folder, "add", "."], check=True)
        result = subprocess.run(staged, cwd=folder, capture_output=True)
        if result.returncode != 1:
            raise SystemExit(f"A new credential was not rejected (scanner exit {result.returncode}).")
    print("Secret-scanner controls passed (clean, Telegram, GitHub, exact-line exclusion, new exposure).")


if __name__ == "__main__":
    main()
