# Environment for building with the threaded Pyodide (sourced by build.sh and
# polars.sh): its Emscripten, PYODIDE_ROOT, -pthread everywhere, and Rust.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

