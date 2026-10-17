"""User-requested unlocks committed by the native character grant operation."""

# Reading guide: Native unlock recovery: return requested character grants through
# native operations.
# Editing notes: Keep pending grants separate from already committed ownership to avoid
# duplicate rewards.
# Checks: offline/test_inventory_transactions.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy


def pending(save):
    """
    Return the requested native character operation only while its grant is pending.
    """
    with save.lock:
        acknowledged = save.state.get("acknowledgedOperations", {})
        owned = {r["pcId"] for r in save.state["tables"].get("UserPC", [])}
        return [
            copy.deepcopy(op)
            for op in save.state.get("accountUnlocks", [])
            if str(op["id"]) not in acknowledged
            and any(r["pcId"] not in owned for r in op["parameters"]["UserPC"])
        ]
