#!/bin/zsh
# Launch the folder-local Python coordinator with a clean Python environment.
# Keep this script beside its existing project paths; see docs/05-source-guide.md.
set -eu
ROOT_DIR="${0:A:h}"
cd "$ROOT_DIR"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
export PYTHONNOUSERSITE=1
exec "$ROOT_DIR/runtime/python/bin/python3.10" -B "$ROOT_DIR/launcher/game.py"
