#!/usr/bin/env bash
# Build a threaded Pyodide (and, with a package name, a threaded package recipe).
#
# Usage, from the repo root:
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build.sh             # Pyodide
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build.sh numpy       # a package (RECIPES=<dir> for pyodide-recipes)
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
# Every object must be built for shared memory, and some recipes set their own
# CFLAGS, so have emcc add -pthread to every compile and link
export EMCC_CFLAGS="${EMCC_CFLAGS:-} -pthread"
# CMake 4 refuses projects declaring support for CMake < 3.5 (libyaml)
export CMAKE_POLICY_VERSION_MINIMUM=3.5
# Rust (a nightly with rust-src, installed in build/threads/rust): the standard
# library is rebuilt with the package, with atomics (RUSTFLAGS, patch-pyodide.py)
export RUSTUP_HOME="$ROOT/build/threads/rust/rustup"
export CARGO_HOME="$ROOT/build/threads/rust/cargo"
export PATH="$CARGO_HOME/bin:$PATH"
export CARGO_UNSTABLE_BUILD_STD="std,panic_unwind"
# A newer toolchain (RUST_TOOLCHAIN=..., e.g. for polars) has no prebuilt
# Pyodide sysroot to download; the standard library is rebuilt anyway
if [ -n "${RUST_TOOLCHAIN:-}" ]; then
    export RUST_EMSCRIPTEN_TARGET_URL=""
fi
# scipy's recipe runs gfortran as a front end (f2c does the compiling); take
# conda-forge's from pixi's cache rather than installing one
if ! command -v gfortran >/dev/null; then
    PATH="$(pixi exec --spec gfortran -- sh -c 'dirname "$(command -v gfortran)"'):$PATH"
    export PATH
fi
export EMCC_CORES="${EMCC_CORES:-12}"

cd "$PYODIDE"
if [ $# -eq 0 ]; then
    make all-but-packages
elif [ "$1" = "--make" ]; then
    shift
    make "$@"
else
    # RECIPES=build/threads/recipes/packages for pyodide-recipes (napari's
    # dependencies); INSTALL_DIR lets two builds run at once without both
    # writing dist/pyodide-lock.json (merge with threads/merge_lock.py)
    pyodide build-recipes "$@" --recipe-dir "${RECIPES:-packages}" --install \
        --install-dir "${INSTALL_DIR:-dist}" \
        --n-jobs "$PYODIDE_JOBS" --log-dir "$ROOT/build/threads/logs/recipes"
fi
