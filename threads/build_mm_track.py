"""Build the mm_track wheel, and constraints that install its tested dependencies.

Usage, from the repo root:
  pixi run --manifest-path qt-build/pixi.toml python threads/build_mm_track.py <mm_track checkout>

Writes build/threads/dist-mmtrack/mm_track-*.whl and constraints.txt: every
package mm_track's uv.lock pins, at that version, except those the threaded
Pyodide builds itself (its pyodide-lock.json), which keep their own, and those
whose environment markers leave them out in Pyodide. micropip would otherwise
take the newest release of everything from PyPI.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "threads" / "dist-mmtrack"
LOCK = ROOT / "build" / "threads" / "pyodide" / "dist" / "pyodide-lock.json"
PYODIDE = {
    "sys_platform": "emscripten",
    "platform_system": "Emscripten",
    "platform_machine": "wasm32",
    "os_name": "posix",
    "python_version": "3.13",
    "python_full_version": "3.13.2",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}

checkout = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("mm_track-*.whl"):
    old.unlink()
subprocess.run(["uv", "build", "-q", "--wheel", "-o", str(OUT)], cwd=checkout, check=True)

built = set(json.loads(LOCK.read_text())["packages"])
exported = subprocess.run(
    ["uv", "export", "-q", "--no-hashes", "--no-emit-project", "--no-default-groups"],
    cwd=checkout,
    check=True,
    capture_output=True,
    text=True,
).stdout
constraints = []
for line in exported.splitlines():
    match = re.match(r"([A-Za-z0-9_.-]+)==([^ ;]+)(?:\s*;\s*(.*))?", line)
    if not match or re.sub(r"[-_.]+", "-", match[1]).lower() in built:
        continue
    if match[3] and not Marker(match[3]).evaluate(PYODIDE):
        continue
    constraints.append(f"{match[1]}=={match[2]}")
(OUT / "constraints.txt").write_text("\n".join(constraints) + "\n")
print(f"{next(OUT.glob('mm_track-*.whl')).name}, {len(constraints)} constraints")
