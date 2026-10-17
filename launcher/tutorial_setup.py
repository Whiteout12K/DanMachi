"""One bounded reload when native first-account setup omits its starter grant."""

# Reading guide: First-account startup observer: recognize the missing starter grant and
# request one bounded reload.
# Editing notes: Do not turn this into an unconditional restart loop; existing accounts
# should pass through.
# Checks: launcher/tests/test_tutorial_setup.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import sys
from pathlib import Path
from types import SimpleNamespace
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "offline"))
from tutorial_starter import pending


class SetupReload:
    """Track startup observations and allow at most one starter-recovery reload."""

    def __init__(self, state):
        self.enabled = not bool(state.get("tables", {}).get("UserInfo"))
        self.first_pending = None
        self.used = False

    def observe(self, state, now):
        if not self.enabled or self.used:
            return False
        operation = pending(SimpleNamespace(state=state, lock=threading.RLock()))
        if operation is None:
            self.first_pending = None
            return False
        if self.first_pending is None:
            self.first_pending = now
        if now - self.first_pending < 5:
            return False
        self.used = True
        return True
