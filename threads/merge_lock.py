"""Copy packages built into another folder into dist/ and its pyodide-lock.json.

Usage: python threads/merge_lock.py <dist> <other-install-dir> [...]

Each folder holds wheels and a pyodide-lock.json, as written by
`pyodide build-recipes --install --install-dir`. Wheels are copied into <dist>
and their lock entries added to <dist>/pyodide-lock.json. A folder without a
pyodide-lock.json (`pyodide build --outdir`, as for polars) gets an entry for
each wheel made from the wheel itself.
"""

import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


def lock_name(name: str) -> str:
    """A package name as the lock file keys it (PEP 503 normalized)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_entry(wheel: Path) -> dict:
    """A lock entry for a wheel with no lock of its own."""
    name, version = wheel.name.split("-")[:2]
    with zipfile.ZipFile(wheel) as archive:
        top_level = sorted(
            {
                path.split("/")[0].removesuffix(".py")
                for path in archive.namelist()
                if not path.split("/")[0].endswith((".dist-info", ".data"))
            }
        )
    return {
        "name": lock_name(name),
        "version": version,
        "file_name": wheel.name,
        "install_dir": "site",
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "package_type": "package",
        "imports": top_level,
        "depends": [],
        "unvendored_tests": False,
    }


dist = Path(sys.argv[1])
lock_path = dist / "pyodide-lock.json"
lock = json.loads(lock_path.read_text())

for other in map(Path, sys.argv[2:]):
    if (other / "pyodide-lock.json").exists():
        packages = json.loads((other / "pyodide-lock.json").read_text())["packages"]
    else:
        packages = {
            lock_name(wheel.name.split("-")[0]): wheel_entry(wheel)
            for wheel in sorted(other.glob("*.whl"))
        }
    for name, package in packages.items():
        source = other / package["file_name"]
        if source.exists():
            shutil.copy2(source, dist / package["file_name"])
        lock["packages"][name] = package
        print(f"{name} {package['version']} from {other}")

lock_path.write_text(json.dumps(lock, indent=2))
