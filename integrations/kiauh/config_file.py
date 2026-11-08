"""Remove only Indus3D's config entries, retaining a backup before any edit."""

import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile
import time


def remove_entry(path, entry):
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    header = re.compile(r"^\s*\[([^]]+)\]\s*(?:[#;].*)?$")
    output = []
    removing = False
    for line in lines:
        match = header.match(line.rstrip("\r\n"))
        if match:
            removing = match.group(1).strip() == entry
            if removing:
                continue
        # Includes have no body: remove that one line, not following comments.
        if removing and entry.startswith("include "):
            removing = False
        if not removing:
            output.append(line)
    updated = "".join(output)
    if original == updated:
        return None
    backup = path.with_name(f"{path.name}.indus3d-backup-{time.time_ns()}")
    shutil.copy2(path, backup)
    stat = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), stat.st_mode & 0o777)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), stat.st_uid, stat.st_gid)
            stream.write(updated)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("entry", choices=("update_manager indus3d", "include indus3d.cfg"))
    args = parser.parse_args()
    backup = remove_entry(args.file, args.entry)
    print(f"Backup: {backup}" if backup else "No matching entry; configuration unchanged")
