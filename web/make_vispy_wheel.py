"""Write web/wheels/vispy-<version>-py3-none-any.whl from vispy's source package.

vispy only publishes platform wheels and an sdist, because of one Cython
extension (the CPU text distance field). wasm_shims.py replaces that
extension, so the rest of vispy can be packaged as plain Python. The
freetype-py requirement is dropped too: wasm_shims draws glyphs with Qt.
"""

import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = sys.argv[1] if len(sys.argv) > 1 else "0.16.2"
OUT_DIR = Path(__file__).resolve().parent / "wheels"
SKIP_SUFFIXES = (".pyx", ".c", ".so", ".pyd")

with urllib.request.urlopen(f"https://pypi.org/pypi/vispy/{VERSION}/json") as response:
    sdist_url = next(
        u["url"] for u in json.load(response)["urls"] if u["packagetype"] == "sdist"
    )
with urllib.request.urlopen(sdist_url) as response:
    sdist = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")

prefix = f"vispy-{VERSION}/"
files = {}
metadata = None
for member in sdist.getmembers():
    if not member.isfile():
        continue
    name = member.name.removeprefix(prefix)
    if name == "PKG-INFO":
        metadata = sdist.extractfile(member).read().decode()
    elif name.startswith("vispy/") and not name.endswith(SKIP_SUFFIXES):
        files[name] = sdist.extractfile(member).read()

metadata = "\n".join(
    line for line in metadata.splitlines() if line != "Requires-Dist: freetype-py"
) + "\n"
dist_info = f"vispy-{VERSION}.dist-info"
files[f"{dist_info}/METADATA"] = metadata.encode()
files[f"{dist_info}/WHEEL"] = (
    b"Wheel-Version: 1.0\nGenerator: napari-wasm\nRoot-Is-Purelib: true\n"
    b"Tag: py3-none-any\n"
)


def record_line(name, data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode()},{len(data)}"


record = [record_line(n, d) for n, d in files.items()] + [f"{dist_info}/RECORD,,"]
files[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()

OUT_DIR.mkdir(exist_ok=True)
wheel = OUT_DIR / f"vispy-{VERSION}-py3-none-any.whl"
with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, data in files.items():
        zf.writestr(name, data)
print(f"{wheel} ({wheel.stat().st_size // 1024} KiB, {len(files)} files)")
