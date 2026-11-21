"""Read the registered macOS WatchPaths agent for the displayed inbox."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path


def watch_status(inbox: Path) -> str:
    if sys.platform != "darwin":
        return "unavailable"
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/com.print-edit.ingest"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if result.returncode:
            return "inactive" if "could not find service" in result.stderr.lower() else "unknown"
        # A loaded WatchPaths job is armed even when its one-shot ingest process is idle.
        for line in result.stdout.splitlines():
            key, sep, value = line.strip().partition(" = ")
            if key == "path" and sep:
                with Path(value).open("rb") as f:
                    config = plistlib.load(f)
                if config.get("Label") != "com.print-edit.ingest":
                    return "unknown"
                paths = [Path(p).resolve() for p in config.get("WatchPaths", [])]
                return "active" if inbox.resolve() in paths else "inactive"
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, ValueError):
        pass
    return "unknown"
