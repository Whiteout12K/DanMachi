"""Compatibility entry point for the confirmed player-deletion tool."""

# Reading guide: Compatibility entry point for the explicit account deletion utility.
# Editing notes: Running this is an account lifecycle action, not a repair or test. Use
# User Data tools and their confirmation flow.
# Checks: offline/test_user_data.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import sys
from user_data import main

if __name__ == "__main__":
    sys.argv[1:] = ["delete", *sys.argv[1:]]
    main()
