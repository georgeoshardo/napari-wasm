"""Post-process a threaded pyodide.asm.js.

Pyodide drops the last 7 lines of pyodide.asm.js to remove Emscripten's
module-export block. A threaded build has more after that block: the lines that
start the runtime inside each worker (`isPthread && _createPyodideModule();`),
which must stay. This removes the block itself instead, and gives the workers
what Pyodide's start-up code expects:

- Workers start the runtime with no settings, but Pyodide's start-up code adds
  to Module.preRun (which workers never run) and to Module.API, and reads
  API.runtimeEnv, which the main thread computes in pyodide.mjs.
- The main thread instantiates WebAssembly itself and adds a `sentinel` import
  module; workers use Emscripten's own instantiation, so it's added there too.
  Pyodide's JavaScript version of the sentinel (its fallback on iOS) is used.
  Sentinel values never cross threads, so each worker can have its own.
- Each thread has its own function table. At start-up CPython builds a helper
  (count_args, used on every call from Python into C), adds it to the main
  thread's table and stores its slot in shared memory. On its first run, each
  worker builds the helper too and puts it in the same slot.

Usage: python fix_asm_js.py dist/pyodide.asm.js
"""

import re
import sys
from pathlib import Path

WORKER_SETTINGS = """{
  preRun: [],
  API: {
    config: {},
    runtimeEnv: {
      IN_NODE: false, IN_BUN: false, IN_DENO: false, IN_SHELL: false,
      IN_SAFARI: /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent),
      IN_NODE_COMMONJS: false, IN_NODE_ESM: false,
      IN_BROWSER: true, IN_BROWSER_MAIN_THREAD: false, IN_BROWSER_WEB_WORKER: true,
    },
  },
}"""

WORKER_SENTINEL = (
    "(() => { const marker = Symbol('error marker'); "
    "return { create_sentinel: () => marker, is_sentinel: (value) => value === marker }; })()"
)

WORKER_FIRST_RUN = """
growMemViews();
const countArgsSlot = HEAP32[(__PyRuntime + HEAP32[__PyEM_EMSCRIPTEN_COUNT_ARGS_OFFSET / 4]) / 4];
const countArgs = countArgsSlot && getPyEMCountArgsPtr();
if (countArgs && countArgs !== countArgsSlot) {
  if (wasmTable.length <= countArgsSlot) wasmTable.grow(countArgsSlot + 1 - wasmTable.length);
  setWasmTableEntry(countArgsSlot, getWasmTableEntry(countArgs));
}
"""

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old, new):
    global text
    if text.count(old) != 1:
        sys.exit(f"{path}: expected one {old!r}, found {text.count(old)}")
    text = text.replace(old, new)


block = re.compile(
    r"if \(typeof exports === 'object' && typeof module === 'object'\) \{.*?"
    r"define\(\[\], \(\) => \w+\);\n",
    re.S,
)
text, count = block.subn("", text)
if count != 1:
    sys.exit(f"{path}: expected one module-export block, found {count}")

replace_once(
    "isPthread && _createPyodideModule();",
    f"isPthread && _createPyodideModule({WORKER_SETTINGS});",
)
replace_once(
    "var instance=new WebAssembly.Instance(module,getWasmImports());",
    f"var instance=new WebAssembly.Instance(module,{{...getWasmImports(),sentinel:{WORKER_SENTINEL}}});",
)
replace_once(
    "if(!initializedJS){initializedJS=true}",
    f"if(!initializedJS){{initializedJS=true;{WORKER_FIRST_RUN}}}",
)
path.write_text(text)
