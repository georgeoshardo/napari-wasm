#!/usr/bin/env bash
# Build Qt and PyQt6 with threads and link them into the threaded Pyodide.
#
# Usage, from the repo root, after threads/build.sh has built Pyodide:
#   pixi run --manifest-path qt-build/pixi.toml bash threads/build-qt.sh [qt|pyqt|pyodide]
#
# Runs qt-build/build.sh with THREADS=1, building in build/threads/qt, reusing
# the Qt sources already cloned by the main build, and linking into
# build/threads/pyodide.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export THREADS=1
export BUILD_DIR="$ROOT/build/threads/qt"
export QT_SRC="$ROOT/qt-build/build/sources/qt6"
export PYODIDE_SRC="$ROOT/build/threads/pyodide"
exec bash "$ROOT/qt-build/build.sh" "$@"
