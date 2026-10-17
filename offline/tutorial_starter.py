"""Repair an interrupted initial Bell grant through the native unit operation."""

# Reading guide: First-unit recovery: prepare the original Bell starter operation when
# initial setup was interrupted.
# Editing notes: Keep the repair idempotent and scoped to the starter; it must not
# refill an existing account.
# Checks: offline/test_tutorial_starter.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy

BELL = 1011001001
OPERATION_ID = 100000000


def pending(save):
    """
    Return the original Bell starter grant only until native ownership confirms it.
    """
    with save.lock:
        state = save.state
        tables = state["tables"]
        if tables.get("UserPC") or not tables.get("UserInfo"):
            return None
        tutorial = next(
            (
                r
                for r in tables.get("UserTutorial", [])
                if r.get("tutorialId") == 780010001
            ),
            None,
        )
        party = next((r for r in tables.get("UserParty", []) if r.get("id") == 1), None)
        if not tutorial or tutorial.get("isEnd") or not party:
            return None
        if not any(
            r.get("pcId") == BELL and r.get("type") == 1 for r in party.get("slots", [])
        ):
            return None
        if str(OPERATION_ID) in state.get("acknowledgedOperations", {}):
            return None
        # Generic native PC grant, also used by lottery rewards. The native
        # master-data constructor supplies stats/jobs/skills; no tutorial flags
        # or owned-character rows are manufactured by the server.
        return {
            "id": OPERATION_ID,
            "type": 1001,
            "signature": OPERATION_ID,
            "token": "",
            "parameters": {
                "UserPC": [{"pcId": BELL}],
                "UserLimitBreakItem": [],
                "UserHeroSublimatePCs": [],
                "UserCommunicationCharacter": [],
            },
        }
