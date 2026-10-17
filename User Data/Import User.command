#!/bin/zsh
# Run the matching account action through offline/user_data.py; that module validates data and controls the game lock.
# Keep this script beside its existing project paths; see docs/05-source-guide.md.
set -eu
project_dir="${0:A:h:h}"
cd "$project_dir"
"$project_dir/runtime/python/bin/python3.10" -B "$project_dir/offline/user_data.py" import
echo "Press Return to close."
read answer
