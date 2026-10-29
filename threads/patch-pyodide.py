"""Patch a Pyodide 0.29.3 checkout to build with WebAssembly threads (pthreads).

Usage: python threads/patch-pyodide.py <pyodide-dir> [<existing-emsdk-dir>]

- CPython is configured with --enable-wasm-pthreads.
- -pthread is added to Pyodide's base compile and link flags. Packages built
  with `pyodide build-recipes` in this checkout get the same flags, which they
  need: a module built without shared memory can't be loaded into one built
  with it.
- Pyodide's trimming of pyodide.asm.js is replaced so that it keeps the lines
  a threaded build needs and sets up the workers (fix_asm_js.py), and the
  workers are told where pyodide.asm.js is.
- The sqlite3 recipe links Emscripten's threaded sqlite.
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
# Emscripten starts each worker from the URL of the script that defined the
# runtime, which it takes from document.currentScript; Pyodide loads
# pyodide.asm.js with import(), where that's empty, so pass the URL instead
replace_once(root / "src" / "js" / "emscripten-settings.ts",
             "    thisProgram: config._sysExecutable,\n",
             "    thisProgram: config._sysExecutable,\n"
             "    // @ts-ignore\n"
             "    mainScriptUrlOrBlob: `${config.indexURL}pyodide.asm.js`,\n")
# the sqlite3 recipe links Emscripten's single-threaded sqlite port by name
sqlite = root / "packages" / "sqlite3" / "meta.yaml"
replace_once(sqlite, "embuilder build sqlite3 --pic", "embuilder build sqlite3-mt --pic")
replace_once(sqlite, "-sUSE_SQLITE3 -lsqlite3\n", "-sUSE_SQLITE3 -lsqlite3-mt\n")
# Pyodide cuts the last 7 lines of pyodide.asm.js to drop Emscripten's
# module-export block; in a threaded build that cuts the lines that start the
# runtime in each worker instead. fix_asm_js.py does it properly and sets the
# workers up.
fix_asm_js = Path(__file__).resolve().parent / "fix_asm_js.py"
replace_once(root / "Makefile",
             "\t$(SED) -i -n -e :a -e '1,7!{P;N;D;};N;ba' dist/pyodide.asm.js",
             f"\tpython3 {fix_asm_js} dist/pyodide.asm.js")

if len(sys.argv) > 2:
    emsdk = root / "emsdk" / "emsdk"
    if not emsdk.exists():
        emsdk.symlink_to(Path(sys.argv[2]).resolve())
    replace_once(root / "pyodide_env.sh", "export _EMCC_CCACHE=1",
                 "command -v ccache >/dev/null 2>&1 && export _EMCC_CCACHE=1")

print(f"patched {root}")
