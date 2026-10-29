"""Write web/wheels/numba-<version>-py3-none-any.whl, a stand-in for numba.

numba compiles Python to machine code with LLVM at run time, which a browser
can't do. tracksdata imports it for a few helpers written as plain Python over
numpy arrays (``@njit``, ``types``, ``typed.List``/``typed.Dict``); with the
stand-in they run as ordinary Python: the same results, more slowly. The
version is numba's with a local label, so that requirements on numba resolve.
"""

import base64
import hashlib
import sys
import zipfile
from pathlib import Path

VERSION = (sys.argv[1] if len(sys.argv) > 1 else "0.67.0") + "+python"
OUT_DIR = Path(__file__).resolve().parent / "wheels"

INIT = '''"""Stand-in for numba: decorated functions run as plain Python."""

from numba import typed, types

__version__ = "VERSION"


def njit(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda function: function


jit = generated_jit = vectorize = guvectorize = cfunc = njit
prange = range

__all__ = ["cfunc", "generated_jit", "guvectorize", "jit", "njit", "prange", "typed", "types", "vectorize"]
'''.replace("VERSION", VERSION)

TYPES = '''"""numba.types: type objects only appear in signatures and type arguments."""


class Type:
    def __init__(self, name):
        self.name = name

    def __getitem__(self, item):
        return Type(f"{self.name}[...]")

    def __call__(self, *args, **kwargs):
        return Type(f"{self.name}(...)")

    def __repr__(self):
        return self.name


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    return Type(name)
'''

TYPED = '''"""numba.typed: a typed List and Dict are a list and a dict."""


class List(list):
    @classmethod
    def empty_list(cls, item_type=None, allocated=None):
        return cls()


class Dict(dict):
    @classmethod
    def empty(cls, key_type=None, value_type=None, n_keys=None):
        return cls()
'''

files = {
    "numba/__init__.py": INIT.encode(),
    "numba/types.py": TYPES.encode(),
    "numba/typed.py": TYPED.encode(),
}
dist_info = f"numba-{VERSION}.dist-info"
files[f"{dist_info}/METADATA"] = (
    f"Metadata-Version: 2.1\nName: numba\nVersion: {VERSION}\n"
    "Summary: Stand-in for numba that runs functions as plain Python\n"
).encode()
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
wheel = OUT_DIR / f"numba-{VERSION}-py3-none-any.whl"
with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, data in files.items():
        zf.writestr(name, data)
print(f"{wheel} ({len(files)} files)")
