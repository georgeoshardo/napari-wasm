"""Copy packages built into another folder into dist/ and its pyodide-lock.json.

Usage: python threads/merge_lock.py <dist> <other-install-dir> [...]

Each folder holds wheels and a pyodide-lock.json, as written by
`pyodide build-recipes --install --install-dir`. Wheels are copied into <dist>
and their lock entries added to <dist>/pyodide-lock.json.
"""

import json
import shutil
import sys
from pathlib import Path

dist = Path(sys.argv[1])
lock_path = dist / "pyodide-lock.json"
lock = json.loads(lock_path.read_text())

for other in map(Path, sys.argv[2:]):
    other_lock = json.loads((other / "pyodide-lock.json").read_text())
    for name, package in other_lock["packages"].items():
        source = other / package["file_name"]
        if source.exists():
            shutil.copy2(source, dist / package["file_name"])
        lock["packages"][name] = package
        print(f"{name} {package['version']} from {other}")

lock_path.write_text(json.dumps(lock, indent=2))
