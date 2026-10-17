"""Keep the retained beginner draw available until its native grant commits."""

# Reading guide: Beginner-banner visibility: keep the original offer available while its
# tutorial grant is incomplete.
# Editing notes: Do not use this tutorial gate for permanent standard ticket banners.
# Checks: offline/test_tutorial_banner.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

BANNER_ID = 171001765
DRAW_OPERATION_ID = 100000001


def available(state):
    # Reserving a choice is not completion: a failed/restarted native grant
    # must retain the banner so the same reserved choice can be retried.
    """Return whether the original beginner grant still needs its native banner."""
    return not (
        state.get("tutorialDraw")
        and str(DRAW_OPERATION_ID) in state.get("acknowledgedOperations", {})
    )
