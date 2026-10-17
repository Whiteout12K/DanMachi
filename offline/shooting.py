"""Local service replies for the retained Ais WAR native minigame.

The client owns its shooting-game scores, coins, unlocks and story state and
commits them through user_data/push. Completion acknowledges the run without
granting those a second time. Remote-player rankings are empty offline.
"""

# Reading guide: Ais WAR protocol replies: provide playable IDs and acknowledge native
# minigame requests.
# Editing notes: The native client owns scores, coins and unlocks. Do not grant a second
# reward on completion.
# Checks: offline/test_shooting.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools

ACTIONS = ("shooting/ranking/get", "shooting/stage/complete")


@functools.lru_cache(maxsize=1)
def playable_ids():
    """Read the original retained shooting-game stage identities."""
    import rebuild_master as master
    from build_gacha import value

    table = master.table("shootingGamePc")
    return {value(table, row, 0) for row in master.rows(table)}


def handle(action, request):
    """
    Answer local minigame requests while leaving score/reward commits to native
    pushes.
    """
    if action == "shooting/ranking/get":
        # DomainYokoshuRankingDataRepository consumes a root ranking array.
        return {"code": 0, "ranking": []}
    if action == "shooting/stage/complete":
        pc, score = request.get("pcId"), request.get("score")
        if (
            type(pc) is not int
            or pc not in playable_ids()
            or type(score) is not int
            or not 0 <= score < 2**63
        ):
            return {"code": 1003}
        return {"code": 0, "data": {}, "dataTokens": {}, "operations": [], "dones": []}
    raise ValueError("Unsupported shooting action")
