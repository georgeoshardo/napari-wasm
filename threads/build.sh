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

source "$(dirname "$0")/env.sh"

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
