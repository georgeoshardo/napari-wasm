"""Pack the threaded build's files that the site loads, for the Pages workflow.

Usage, from the repo root, after building with threads/build.sh:
  python3 threads/site_files.py
  gh release upload threaded-build build/threads/site-files.tar.gz --clobber

Writes build/threads/site-files.tar.gz: Pyodide's own files and every package
in its lock file except the unvendored tests, at their paths in this repo.
Building them takes hours, so the workflow downloads them from the release.
"""

import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "build" / "threads" / "pyodide" / "dist"
OUT = ROOT / "build" / "threads" / "site-files.tar.gz"

lock = json.loads((DIST / "pyodide-lock.json").read_text())
names = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
names += sorted(
    {package["file_name"] for name, package in lock["packages"].items() if not name.endswith("-tests")}
)
with tarfile.open(OUT, "w:gz") as archive:
    for name in names:
        archive.add(DIST / name, arcname=(DIST / name).relative_to(ROOT).as_posix())
print(f"{OUT.relative_to(ROOT)}: {len(names)} files, {OUT.stat().st_size / 1e6:.0f} MB")
