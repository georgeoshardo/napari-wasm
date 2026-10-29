#!/usr/bin/env bash
# Build a threaded Pyodide (and, with a package name, a threaded package recipe).
#
# Usage, from the repo root:
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build.sh             # Pyodide
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build.sh numpy       # a package
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build.sh --make dist/pyodide.asm.js
#
# Expects build/threads/pyodide to be a Pyodide 0.29.3 checkout patched with
# threads/patch-pyodide.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYODIDE="$ROOT/build/threads/pyodide"
emsdk_dir="$PYODIDE/emsdk/emsdk"

unset EMSDK EM_CONFIG EMSDK_NODE EMSDK_PYTHON PYTHON 2>/dev/null || true
export EMSDK="$emsdk_dir"
export EM_CONFIG="$emsdk_dir/.emscripten"
export PATH="$emsdk_dir/upstream/emscripten:$emsdk_dir/upstream/bin:$emsdk_dir/node/22.16.0_64bit/bin:$PATH"
export PYODIDE_ROOT="$PYODIDE"
export PYODIDE_JOBS="${PYODIDE_JOBS:-12}"
export EMCC_CORES="${EMCC_CORES:-12}"

cd "$PYODIDE"
if [ $# -eq 0 ]; then
    make all-but-packages
elif [ "$1" = "--make" ]; then
    shift
    make "$@"
else
    pyodide build-recipes "$@" --recipe-dir packages --install --install-dir dist --n-jobs "$PYODIDE_JOBS"
fi
