#!/usr/bin/env bash
# Build polars' runtime (polars-runtime-32) for the threaded Pyodide.
#
# Usage, from the repo root:
#   pixi run --manifest-path qt-build/pixi.toml bash threads/polars.sh
#
# Polars has built for Pyodide only up to 1.33: since then its streaming engine
# needs tokio's networking (its file cache reaches object_store and an HTTP
# client), whose I/O layer, mio, has no Emscripten backend. The threaded build
# has threads and a poll() that works across them (vfd.c), so mio, tokio and
# reqwest are built for Emscripten as the musl system it is (patched copies,
# below); nothing opens a socket in the browser. The OS clipboard and the
# custom allocator are left out, and the extension module is built for this
# Python only (not abi3), as Pyodide's cross-build environment expects. The
# wheel goes to build/threads/dist-polars; polars itself is pure Python and
# comes from PyPI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="py-1.44.1"
TOOLCHAIN="nightly-2026-08-18"  # polars' rust-toolchain.toml at $TAG
SRC="$ROOT/build/threads/src/polars"
OUT="$ROOT/build/threads/dist-polars"

CRATES="$ROOT/build/threads/src/crates"

if [ ! -d "$SRC" ]; then
    git clone --depth 1 --branch "$TAG" https://github.com/pola-rs/polars.git "$SRC"
fi
git -C "$SRC" checkout -q -- .
mkdir -p "$CRATES"
for crate in mio-1.2.2 tokio-1.53.1 reqwest-0.12.28; do
    rm -rf "${CRATES:?}/$crate"
    curl -sL "https://static.crates.io/crates/${crate%-*}/$crate.crate" | tar xz -C "$CRATES"
done

python3 - "$CRATES" "$SRC" <<'EOF'
import sys
from pathlib import Path

crates, src = Path(sys.argv[1]), Path(sys.argv[2])
mio, tokio, reqwest = crates / "mio-1.2.2", crates / "tokio-1.53.1", crates / "reqwest-0.12.28"


def replace(path, old, new, count=1):
    text = path.read_text()
    if text.count(old) != count:
        sys.exit(f"{path}: expected {count} of {old!r}, found {text.count(old)}")
    path.write_text(text.replace(old, new))


# mio: its poll(2) selector and pipe waker (cfg flags in RUSTFLAGS), and
# accept4 as on Linux
replace(mio / "src/lib.rs",
        '#[cfg(all(target_family = "wasm", not(target_os = "wasi")))]',
        '#[cfg(all(target_family = "wasm", not(target_os = "wasi"), not(target_os = "emscripten")))]')
replace(mio / "src/sys/unix/tcp.rs",
        '        target_os = "linux",\n        target_os = "netbsd",',
        '        target_os = "linux",\n        target_os = "emscripten",\n        target_os = "netbsd",')
# tokio: its networking and multi-threaded runtime with socket2, and Unix-socket
# peer credentials as on its other single-process targets
replace(tokio / "src/lib.rs",
        '    not(tokio_unstable),\n    target_family = "wasm",\n    any(\n        feature = "fs",',
        '    not(tokio_unstable),\n    target_family = "wasm",\n    not(target_os = "emscripten"),\n    any(\n        feature = "fs",')
replace(tokio / "Cargo.toml",
        """[target.'cfg(any(not(target_family = "wasm"), all(target_os = "wasi", not(target_env = "p1"))))'.dependencies.socket2]""",
        """[target.'cfg(any(not(target_family = "wasm"), target_os = "emscripten", all(target_os = "wasi", not(target_env = "p1"))))'.dependencies.socket2]""")
replace(tokio / "src/net/unix/ucred.rs",
        '    target_os = "vita",\n    target_os = "hurd"\n))]',
        '    target_os = "vita",\n    target_os = "hurd",\n    target_os = "emscripten"\n))]', count=2)
# reqwest: its native client (its browser one is built on wasm-bindgen, which
# doesn't support Emscripten)
for path in [reqwest / "Cargo.toml", *(reqwest / "src").rglob("*.rs")]:
    text = path.read_text()
    if 'target_arch = "wasm32"' in text:
        path.write_text(text.replace(
            'target_arch = "wasm32"', 'all(target_arch = "wasm32", not(target_os = "emscripten"))'))
replace(src / "Cargo.toml", "\n[patch.crates-io]\n",
        f'\n[patch.crates-io]\nmio = {{ path = "{mio}" }}\n'
        f'tokio = {{ path = "{tokio}" }}\nreqwest = {{ path = "{reqwest}" }}\n')

# polars: no OS clipboard or custom allocator, and not abi3
python_crate = src / "crates/polars-python/Cargo.toml"
runtime_crate = src / "py-polars/runtime/polars-runtime-32/Cargo.toml"
replace(python_crate, '  "clipboard",\n', "")
replace(python_crate, 'full = ["full_functionality", "fast_alloc"]', 'full = ["full_functionality"]')
replace(runtime_crate, '  "clipboard",\n', "")
replace(runtime_crate, '  "fast_alloc",\n', "")
for path in [python_crate, runtime_crate]:
    replace(path, '"abi3-py310", ', "")
EOF

source "$ROOT/threads/env.sh"
export RUST_TOOLCHAIN="$TOOLCHAIN"
export RUST_EMSCRIPTEN_TARGET_URL=""
# wasm exceptions are the default in this toolchain (no -Z emscripten-wasm-eh)
export RUSTFLAGS="-C link-arg=-sSIDE_MODULE=2 -Z link-native-libraries=yes -C target-feature=+atomics,+bulk-memory,+mutable-globals --cfg mio_unsupported_force_poll_poll --cfg mio_unsupported_force_waker_pipe"
# polars' release profile uses fat LTO, which crashed rustc in polars-pyodide's
# wasm builds
export CARGO_PROFILE_RELEASE_LTO=off

rustup toolchain install "$TOOLCHAIN" --profile minimal --component rust-src --target wasm32-unknown-emscripten
cd "$SRC/py-polars/runtime/polars-runtime-32"
pyodide build --outdir "$OUT"
