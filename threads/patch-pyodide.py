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
- Pipes and eventfds are implemented in the main module, so threads can wake
  each other through them (vfd.c).
- Calls from JavaScript into Python take the GIL and give it back, and the
  main thread doesn't hold it otherwise, so other threads can run while the
  browser has control.
- The main module pre-starts a pool of workers. Starting a thread waits for its
  worker, and a browser only starts a new worker once the main thread returns
  to the event loop, so without a pool the first thread start hangs.
- With an existing Emscripten 4.0.9 toolchain built by another Pyodide 0.29.3
  checkout, that one is linked in instead of building a new one, and ccache is
  left out as in the Qt build.
"""

import shutil
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
# Rust code needs atomics for shared memory; its standard library is compiled
# with the same flags (cargo build-std, set in threads/build.sh)
replace_once(envs, "-Z emscripten-wasm-eh\n",
             "-Z emscripten-wasm-eh -C target-feature=+atomics,+bulk-memory,+mutable-globals\n")
# Pyodide links Emscripten's native libraries by hand (AUTO_NATIVE_LIBRARIES=0);
# with threads, Qt's use of the html5 API needs the C half of it as well
replace_once(envs, "\t-lGL \\\n", "\t-lGL \\\n\t-lhtml5 \\\n")
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
# Pyodide holds the GIL on the main thread all the time, also while the browser
# has control, so other threads only run when the main thread happens to be
# running Python. Pyodide's JavaScript assumes it holds the GIL throughout a
# call into Python and for the C calls it makes afterwards (converting errors,
# reference counts), so the GIL is held per browser task: API.enterPython takes
# it if the task doesn't have it and queues a microtask that gives it back once
# the task's JavaScript is done. It's called on every entry into Python
# (Py_ENTER, pyodide.toPy) and when a suspended Python stack resumes (JSPI).
# While a stack is suspended (run_sync) the GIL stays taken, as it would for a
# C call that blocks without releasing it: releasing it stops the stack from
# resuming.
# Start-up holds the GIL throughout (it makes direct C calls across tasks) and
# hands it over at the end.
ENTER_PYTHON = """
// Hold the GIL for the rest of this browser task (see patch-pyodide.py). The
// thread state that was current is detached and re-attached as it is: while a
// stack is suspended Pyodide has swapped in another one.
let gilPerTask = false;
let holdingForTask = false;
let detachedThreadState = 0;
function giveBackGil() {
  holdingForTask = false;
  if (API.suspendedStacks > 0) {
    // a suspended stack keeps the GIL (releasing it stops run_sync resuming)
    return;
  }
  // @ts-ignore
  detachedThreadState = _PyEval_SaveThread();
}
API.suspendedStacks = 0;
API.enterPython = function () {
  if (!gilPerTask || holdingForTask) {
    return;
  }
  if (detachedThreadState) {
    // @ts-ignore
    _PyEval_RestoreThread(detachedThreadState);
    detachedThreadState = 0;
  }
  holdingForTask = true;
  queueMicrotask(giveBackGil);
};
API.releaseStartupGil = function () {
  gilPerTask = true;
  API.enterPython();
};
"""
replace_once(root / "src" / "js" / "api.ts",
             "API.loadBinaryFile = loadBinaryFile;\n",
             "API.loadBinaryFile = loadBinaryFile;\n" + ENTER_PYTHON)
replace_once(root / "src" / "js" / "types.ts",
             "  rawRun: (code: string) => [number, string];\n",
             "  rawRun: (code: string) => [number, string];\n"
             "  enterPython: () => void;\n"
             "  releaseStartupGil: () => void;\n"
             "  suspendedStacks: number;\n")
replace_once(root / "src" / "core" / "pyproxy.c",
             "#define Py_ENTER()                                                             \\\n"
             "  _check_gil();                                                                \\\n",
             "#define Py_ENTER()                                                             \\\n"
             "  API.enterPython();                                                           \\\n")
# the handlers Pyodide attaches to a JavaScript promise that Python awaits call
# into Python directly, in their own task
for handler in ["function destroy(){\n", "function onFulfilled(res) {\n", "function onRejected(err) {\n"]:
    replace_once(root / "src" / "core" / "pyproxy.c", f"  {handler}",
                 f"  {handler}    API.enterPython();\n")
replace_once(root / "src" / "js" / "api.ts",
             "    let py_result = 0;\n    let result = 0;\n    try {\n"
             "      py_result = Module.js2python_convert(obj, {",
             "    API.enterPython();\n"
             "    let py_result = 0;\n    let result = 0;\n    try {\n"
             "      py_result = Module.js2python_convert(obj, {")
replace_once(root / "src" / "core" / "stack_switching" / "suspenders.c",
             "  const stackState = new StackState();\n",
             "  API.suspendedStacks++;\n  const stackState = new StackState();\n")
replace_once(root / "src" / "core" / "stack_switching" / "suspenders.c",
             "EM_JS(void, restoreState, (JsVal state), {\n",
             "EM_JS(void, restoreState, (JsVal state), {\n"
             "  API.suspendedStacks--;\n  API.enterPython();\n")
replace_once(root / "src" / "js" / "api.ts",
             "  bootstrapFinalized!();\n  return pyodide;\n};",
             "  bootstrapFinalized!();\n"
             "  API.releaseStartupGil();\n"
             "  return pyodide;\n};")
# the sqlite3 recipe links Emscripten's single-threaded sqlite port by name, in
# Pyodide's own recipes and in pyodide-recipes (build/threads/recipes) if there
for recipes in [root / "packages", root.parent / "recipes" / "packages"]:
    sqlite = recipes / "sqlite3" / "meta.yaml"
    if sqlite.exists():
        replace_once(sqlite, "embuilder build sqlite3 --pic", "embuilder build sqlite3-mt --pic")
        replace_once(sqlite, "-sUSE_SQLITE3 -lsqlite3\n", "-sUSE_SQLITE3 -lsqlite3-mt\n")
# pythran 0.19 needs C++17; scipy and scikit-image compile its headers as C++14
replace_once(root / "tools" / "constraints.txt", "cmake < 4\n", "cmake < 4\npythran < 0.19\n")
# pipes and eventfds that threads can share (see vfd.c), linked into the main
# module so that CPython and side modules use them
threads = Path(__file__).resolve().parent
shutil.copy(threads / "vfd.c", root / "src" / "core" / "vfd.c")
(root / "src" / "core" / "sys").mkdir(exist_ok=True)
shutil.copy(threads / "include" / "sys" / "eventfd.h", root / "src" / "core" / "sys" / "eventfd.h")
replace_once(root / "Makefile", "\tsrc/core/main.o  \\\n", "\tsrc/core/main.o  \\\n\tsrc/core/vfd.o  \\\n")
replace_once(root / "Makefile", "-lpyodide src/core/main.o $(MAIN_MODULE_LDFLAGS)",
             "-lpyodide src/core/main.o src/core/vfd.o $(MAIN_MODULE_LDFLAGS)")
# a main module links all of libc, so libc's versions come out of the threaded
# libc (only threaded builds use it)
replace_once(root / "Makefile", "\tembuilder build libgl\n",
             "\tembuilder build libgl\n"
             "\tembuilder build libc-mt --pic\n"
             "\temar d $$(em-config CACHE)/sysroot/lib/wasm32-emscripten/pic/libc-mt.a"
             " read.o write.o close.o poll.o select.o pipe.o pipe2.o fcntl.o dup.o dup2.o dup3.o\n")
# Pyodide cuts the last 7 lines of pyodide.asm.js to drop Emscripten's
# module-export block; in a threaded build that cuts the lines that start the
# runtime in each worker instead. fix_asm_js.py does it properly and sets the
# workers up.
fix_asm_js = threads / "fix_asm_js.py"
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
