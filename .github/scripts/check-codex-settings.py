"""Check the installed Codex configuration from a regular Git checkout."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib


def check(root):
    manifest = json.loads((root / ".codex/codex-settings-manifest.json").read_text())
    if not manifest:
        raise ValueError("The Codex settings manifest is empty.")
    errors = []
    for name, expected in manifest.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            errors.append(f"Missing or invalid installed path: {name}")
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            errors.append(f"Installed file differs from the manifest: {name}")
        if name.endswith(".toml"):
            tomllib.loads(content.decode())
        elif name.endswith(".json"):
            json.loads(content)
    for name in (".codex/hooks.json", ".codex/hooks/harness.py"):
        if name not in manifest:
            errors.append(f"Required manifest entry is missing: {name}")
    compile((root / ".codex/hooks/harness.py").read_bytes(), "harness.py", "exec")
    if errors:
        raise ValueError("\n".join(errors))
    print(f"Checked {len(manifest)} installed Codex settings files.")


if __name__ == "__main__":
    try:
        root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
        check(root)
    except (OSError, ValueError, SyntaxError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
