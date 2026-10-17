"""Finish local player writes after the native Settings exit request."""

# Reading guide: Shutdown handshake: request a local checkpoint and finish native save
# handling before the launcher exits.
# Editing notes: Keep timeouts bounded so a stopped server cannot trap the app on close.
# Checks: launcher/tests/test_save_exit.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import json
import os
import urllib.request
from pathlib import Path

CLIENT_PATHS = (
    "files/ldb",
    "files/kwlt",
    "files/commit_list.dat",
    "shared_prefs",
    "databases",
    "no_backup",
)


def save_before_close(client_root):
    """Request and verify a bounded server checkpoint before the launcher closes."""
    request = urllib.request.Request(
        "http://127.0.0.1:28766/offline/save-checkpoint", data=b"", method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if json.load(response).get("saved") is not True:
            raise RuntimeError("The local server did not confirm the save checkpoint.")
    # The client has exited, so its local databases and preferences are stable.
    # Flush only player files; assets and caches are excluded.
    for name in CLIENT_PATHS:
        path = client_root / name
        if path.is_symlink():
            raise RuntimeError("Unexpected link in player save.")
        if path.is_dir():
            for folder, directories, files in os.walk(path, followlinks=False):
                directory = Path(folder)
                if any((directory / n).is_symlink() for n in directories + files):
                    raise RuntimeError("Unexpected link in player save.")
                for filename in files:
                    with (directory / filename).open("rb") as file:
                        os.fsync(file.fileno())
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        elif path.is_file():
            with path.open("rb") as file:
                os.fsync(file.fileno())
