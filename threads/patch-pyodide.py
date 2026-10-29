"""Patch a Pyodide 0.29.3 checkout to build with WebAssembly threads (pthreads).

Usage: python threads/patch-pyodide.py <pyodide-dir> [<existing-emsdk-dir>]

- CPython is configured with --enable-wasm-pthreads.
- -pthread is added to Pyodide's base compile and link flags. Packages built
  with `pyodide build-recipes` in this checkout get the same flags, which they
  need: a module built without shared memory can't be loaded into one built
  with it.
- The main module pre-starts a pool of workers. Starting a thread waits for its
  worker, and a browser only starts a new worker once the main thread returns
  to the event loop, so without a pool the first thread start hangs.
- With an existing Emscripten 4.0.9 toolchain built by another Pyodide 0.29.3
  checkout, that one is linked in instead of building a new one, and ccache is
  left out as in the Qt build.
"""

import sys
from pathlib import Path

POOL_SIZE = 8


def replace_once(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        sys.exit(f"{path}: expected exactly one {old!r}")
    path.write_text(text.replace(old, new))


root = Path(sys.argv[1]).resolve()
envs = root / "Makefile.envs"

replace_once(envs, "\t-sSUPPORT_LONGJMP \\\n\t$(EXTRA_CFLAGS)",
             "\t-sSUPPORT_LONGJMP \\\n\t-pthread \\\n\t$(EXTRA_CFLAGS)")
replace_once(envs, "export LDFLAGS_BASE=\\\n\t$(OPTFLAGS) \\",
             "export LDFLAGS_BASE=\\\n\t-pthread \\\n\t$(OPTFLAGS) \\")
replace_once(envs, "\t-s MAIN_MODULE=1 \\",
             f"\t-s MAIN_MODULE=1 \\\n\t-s PTHREAD_POOL_SIZE={POOL_SIZE} \\")
replace_once(root / "cpython" / "Makefile", "\t\t\t  --disable-ipv6 \\",
             "\t\t\t  --disable-ipv6 \\\n\t\t\t  --enable-wasm-pthreads \\")

if len(sys.argv) > 2:
    emsdk = root / "emsdk" / "emsdk"
    if not emsdk.exists():
        emsdk.symlink_to(Path(sys.argv[2]).resolve())
    replace_once(root / "pyodide_env.sh", "export _EMCC_CCACHE=1",
                 "command -v ccache >/dev/null 2>&1 && export _EMCC_CCACHE=1")

print(f"patched {root}")
