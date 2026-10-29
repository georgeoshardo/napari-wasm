"""Write web/pyodide-lock.json: the official Pyodide 0.29.3 package set, served from its CDN.

The custom Pyodide build ships an empty lock file. Its ABI matches the official
0.29.3 release (abi_version 2025_0, emscripten_4_0_9, Python 3.13.2), so the
official wheels load as they are; this rewrites each file name to an absolute
CDN URL so the packages don't need to be copied here.
"""

import json
import urllib.request
from pathlib import Path

CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/"
OUT = Path(__file__).resolve().parent / "pyodide-lock.json"

with urllib.request.urlopen(CDN + "pyodide-lock.json") as response:
    lock = json.load(response)

for package in lock["packages"].values():
    package["file_name"] = CDN + package["file_name"]

OUT.write_text(json.dumps(lock, indent=1))
print(f"{OUT}: {len(lock['packages'])} packages, {lock['info']}")
