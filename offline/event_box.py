"""Retained reward-box screens, atomic draws and native grant recovery.

Protocol: original DomainEventBoxRepository callback at 0x2411860 reads
chosenItems and currentStepContents; native reward grants use operation 6000.
All tests and fixtures live outside the real player save.
"""

# Reading guide: Reward boxes: show() initializes screens, draw() reserves currency and
# prizes, recovery() replays pending native grants.
# Editing notes: Finite prize counts and reset-prize requirements come from original
# masters. Payment/progress and request replay must stay atomic.
# Checks: tools/maintain.py test boxes.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy
import functools
import hashlib
from save_store import copy_state, pack


# Original box identities and native screen setup
@functools.lru_cache(maxsize=1)
def definitions():
    """Read original box aliases, ordered steps and content identities."""
    import rebuild_master as m
    from build_gacha import value

    b = m.table("eventBox")
    boxes = {value(b, r, 0): m.text(b, r, 2) for r in m.rows(b)}
    b = m.table("eventBoxStep")
    steps = {}
    for r in m.rows(b):
        steps.setdefault(m.text(b, r, 2), []).append(
            (value(b, r, 3), value(b, r, 0), m.text(b, r, 1))
        )
    b = m.table("eventBoxContent")
    contents = {}
    for r in m.rows(b):
        contents.setdefault(m.text(b, r, 1), []).append(value(b, r, 0))
    return boxes, steps, contents


def show(save, request):
    """Initialize original box rows and accept only a legitimate next-round request."""
    boxes, steps, contents = definitions()
    bid = request.get("eventBoxId")
    if bid not in boxes:
        return {"code": 1003}
    ordered = sorted(steps.get(boxes[bid], []))
    if not ordered:
        return {"code": 1003}
    names = ("UserEventBox", "UserEventBoxStep", "UserEventBoxContent")
    with save.lock:
        state = copy_state(save.state, names)
        user = state["tables"]["UserInfo"][0]["userId"]
        rows = state["tables"].setdefault("UserEventBox", [])
        if not any(r["eventBoxId"] == bid for r in rows):
            rows.append(
                {
                    "userId": user,
                    "eventBoxId": bid,
                    "currentStepId": ordered[0][1],
                    "totalDrawCount": 0,
                }
            )
        box = next(r for r in rows if r["eventBoxId"] == bid)
        requested = request.get("eventBoxStepId", box["currentStepId"])
        if type(requested) is not int or requested not in {
            sid for _, sid, _ in ordered
        }:
            return {"code": 1003}
        if requested != box["currentStepId"]:
            if pending(save):
                return {"code": 1003}
            current = next(
                (
                    i
                    for i, (_, sid, _) in enumerate(ordered)
                    if sid == box["currentStepId"]
                ),
                None,
            )
            if current is None:
                return {"code": 1003}
            next_step = (
                ordered[current + 1][1]
                if current + 1 < len(ordered)
                else next(
                    (sid for _, sid, _ in ordered if repeatable_steps().get(sid)), None
                )
            )
            if requested != next_step:
                return {"code": 1003}
            # Original canReset requires every reset-prize quantity to be drawn.
            requirements = reset_prizes().get(box["currentStepId"], {})
            picked = {
                r["eventBoxContentId"]: r["pickedAmount"]
                for r in state["tables"].get("UserEventBoxContent", [])
            }
            if any(
                picked.get(cid, 0) < quantity for cid, quantity in requirements.items()
            ):
                return {"code": 1003}
            box["currentStepId"] = requested
        step_rows = state["tables"].setdefault("UserEventBoxStep", [])
        content_rows = state["tables"].setdefault("UserEventBoxContent", [])
        step_ids = {r["eventBoxStepId"] for r in step_rows}
        content_ids = {r["eventBoxContentId"] for r in content_rows}
        for _, sid, alias in ordered:
            if sid not in step_ids:
                step_rows.append(
                    {"userId": user, "eventBoxStepId": sid, "drawCount": 0}
                )
            for cid in contents.get(alias, []):
                if cid not in content_ids:
                    content_rows.append(
                        {
                            "userId": user,
                            "eventBoxContentId": cid,
                            "eventBoxStepId": sid,
                            "pickedAmount": 0,
                            "rateVariationState": 0,
                        }
                    )
        for name in names:
            state["tokens"][name] = hashlib.md5(pack(state["tables"][name])).hexdigest()
        save._write(state)
        data = {name: copy.deepcopy(state["tables"][name]) for name in names}
        # The native screen creates UserEventBox locally before requesting show.
        # Only the step/content payload belongs to this response; sending the
        # box again through generic data attempts a duplicate native insertion.
        return {
            "code": 0,
            "data": {},
            "dataTokens": {},
            "operations": [],
            "dones": [],
            "currentStepContents": current_contents(state, bid),
            "UserEventBoxStep": data["UserEventBoxStep"],
            "UserEventBoxContent": data["UserEventBoxContent"],
        }


# Original costs, finite quantities and reset requirements
@functools.lru_cache(maxsize=1)
def draw_definitions():
    """Original item identities, costs, finite quantities and selection weights."""
    import rebuild_master as m
    from build_gacha import value

    aliases = {}
    for name in (
        "currency",
        "statusBoardItem",
        "staminaTicket",
        "expItem",
        "gachaTicket",
        "voteItem",
        "equipmentMaterial",
        "cpItem",
        "keyItem",
        "eventItem",
    ):
        data = m.table(name)
        for row in m.rows(data):
            aliases[m.text(data, row, 1)] = value(data, row, 0)
    data = m.table("eventBox")
    boxes = {
        value(data, r, 0): {
            "item": aliases[m.text(data, r, 3)],
            "cost": value(data, r, 4),
        }
        for r in m.rows(data)
    }
    data = m.table("eventBoxContent")
    contents = {}
    for r in m.rows(data):
        contents[value(data, r, 0)] = {
            "itemId": aliases[m.text(data, r, 3)],
            "amount": value(data, r, 4),
            "limited": bool(value(data, r, 5)),
            "quantity": value(data, r, 6),
            "weight": value(data, r, 8),
        }
    return boxes, contents


@functools.lru_cache(maxsize=1)
def repeatable_steps():
    """Read which original reward-box steps allow another round."""
    import rebuild_master as m
    from build_gacha import value

    data = m.table("eventBoxStep")
    return {value(data, r, 0): bool(value(data, r, 4)) for r in m.rows(data)}


@functools.lru_cache(maxsize=1)
def reset_prizes():
    """Read the finite prizes that must be exhausted before advancing a box."""
    import rebuild_master as m
    from build_gacha import value

    aliases = {
        alias: sid for group in definitions()[1].values() for _, sid, alias in group
    }
    data = m.table("eventBoxContent")
    result = {}
    for row in m.rows(data):
        if value(data, row, 7):
            result.setdefault(aliases[m.text(data, row, 1)], {})[
                value(data, row, 0)
            ] = value(data, row, 6)
    return result


def current_contents(state, bid):
    """Build current native box rates and finite remaining-prize information."""
    contents = draw_definitions()[1]
    sid = next(
        r["currentStepId"]
        for r in state["tables"]["UserEventBox"]
        if r["eventBoxId"] == bid
    )
    rows = [
        r for r in state["tables"]["UserEventBoxContent"] if r["eventBoxStepId"] == sid
    ]
    weights = {
        r["eventBoxContentId"]: (
            contents[r["eventBoxContentId"]]["weight"]
            if not contents[r["eventBoxContentId"]]["limited"]
            or r["pickedAmount"] < contents[r["eventBoxContentId"]]["quantity"]
            else 0
        )
        for r in rows
    }
    total = sum(weights.values())
    return [
        {
            "contentId": r["eventBoxContentId"],
            "rate": weights[r["eventBoxContentId"]] / total if total else 0,
            "rateVariationState": r["rateVariationState"],
        }
        for r in rows
    ]


# Reserved operation replay and table recovery
def pending(save):
    """Return the unacknowledged native reward operation for a reserved box draw."""
    with save.lock:
        last = save.state.get("offlineEventBox", {}).get("last", {})
        operation = last.get("response", {}).get("operation")
        return (
            copy.deepcopy(operation)
            if operation
            and str(operation["id"]) not in save.state.get("acknowledgedOperations", {})
            else None
        )


def recovery(save):
    """Repeat authoritative cost/count rows while a native grant is pending."""
    with save.lock:
        if not pending(save):
            return {}, {}
        names = (
            "UserEventItem",
            "UserEventBox",
            "UserEventBoxStep",
            "UserEventBoxContent",
        )
        return (
            {n: copy.deepcopy(save.state["tables"].get(n, [])) for n in names},
            {n: save.state["tokens"].get(n, "") for n in names},
        )


# Atomic box draw and stale-push protection
def draw(save, request, key):
    """
    Reserve original box prizes and currency together, with durable request replay.
    """
    import secrets
    from save_store import aggregate_items

    bid = request.get("eventBoxId")
    count = request.get("drawCount")
    if type(bid) is not int or type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("Invalid event-box draw")
    boxes, contents = draw_definitions()
    if bid not in boxes:
        raise ValueError("Unknown event box")
    with save.lock:
        state = copy.deepcopy(save.state)
        local = state.setdefault("offlineEventBox", {"sequence": 0})
        last = local.get("last", {})
        if last.get("key") == key:
            if last["request"] != request:
                raise ValueError("Event-box retry differs from reserved request")
            return copy.deepcopy(last["response"])
        if pending(save):
            raise ValueError("Previous event-box grant is still pending")
        box = next(
            (
                r
                for r in state["tables"].get("UserEventBox", [])
                if r["eventBoxId"] == bid
            ),
            None,
        )
        if box is None:
            raise ValueError("Open the event box before drawing")
        sid = box["currentStepId"]
        _, steps, groups = definitions()
        valid_steps = {s for _, s, _ in steps[definitions()[0][bid]]}
        if sid not in valid_steps:
            raise ValueError("Unknown current event-box step")
        alias = next(alias for _, s, alias in steps[definitions()[0][bid]] if s == sid)
        pool = groups[alias]
        rows = {
            r["eventBoxContentId"]: r
            for r in state["tables"].get("UserEventBoxContent", [])
            if r["eventBoxStepId"] == sid
        }
        if set(pool) - rows.keys():
            raise ValueError("Incomplete event-box inventory")
        item = next(
            (
                r
                for r in state["tables"].get("UserEventItem", [])
                if r["eventItemId"] == boxes[bid]["item"]
                and r["userId"] == box["userId"]
            ),
            None,
        )
        cost = count * boxes[bid]["cost"]
        if item is None or item.get("amount", 0) - item.get("reservedAmount", 0) < cost:
            raise ValueError("Not enough event-box currency")
        chosen = []
        rewards = []
        for _ in range(count):
            available = [
                cid
                for cid in pool
                if contents[cid]["weight"] > 0
                and (
                    not contents[cid]["limited"]
                    or rows[cid]["pickedAmount"] < contents[cid]["quantity"]
                )
            ]
            total = sum(contents[cid]["weight"] for cid in available)
            if not total:
                raise ValueError("Event box is empty; reset it before drawing")
            pick = secrets.randbelow(total)
            for cid in available:
                pick -= contents[cid]["weight"]
                if pick < 0:
                    break
            rows[cid]["pickedAmount"] += 1
            chosen.append({"eventBoxContentId": cid})
            rewards.append(
                {"itemId": contents[cid]["itemId"], "amount": contents[cid]["amount"]}
            )
        item["amount"] -= cost
        box["totalDrawCount"] = box.get("totalDrawCount", 0) + count
        step = next(
            r for r in state["tables"]["UserEventBoxStep"] if r["eventBoxStepId"] == sid
        )
        step["drawCount"] += count
        local["sequence"] += 1
        sequence = 500000000 + local["sequence"]
        rewards = aggregate_items(rewards)
        operation = {
            "id": sequence,
            "signature": sequence,
            "token": "",
            "type": 6000,
            "parameters": {
                "issueAmount": sum(
                    r["amount"] for r in rewards if r["itemId"] == 205000001
                ),
                "issueStamina": 0,
                "receivedCostumes": [],
                "receivedItems": rewards,
                "receivedPCs": [],
                "receivedMemorias": [],
                "issueCasinoMedal": 0,
                "UserUnionRaidMedal": [],
                "UserAchievement": [],
            },
        }
        names = (
            "UserEventItem",
            "UserEventBox",
            "UserEventBoxStep",
            "UserEventBoxContent",
        )
        for name in names:
            state["tokens"][name] = hashlib.md5(pack(state["tables"][name])).hexdigest()
        response = {
            "code": 0,
            "chosenItems": chosen,
            "currentStepContents": current_contents(state, bid),
            "operation": operation,
            "data": {n: copy.deepcopy(state["tables"][n]) for n in names},
            "dataTokens": {n: state["tokens"][n] for n in names},
            "operations": [],
            "dones": [],
        }
        # Native API callbacks receive grant parameters after the operation commits.
        operation["parameters"]["chosenItems"] = copy.deepcopy(chosen)
        operation["parameters"]["currentStepContents"] = copy.deepcopy(
            response["currentStepContents"]
        )
        local["last"] = {
            "key": key,
            "request": copy.deepcopy(request),
            "response": response,
        }
        save._write(state)
        return copy.deepcopy(response)


def protect_pending(state, previous):
    """Do not let a delayed pre-draw push undo reserved payment/progress."""
    from save_store import TABLE_IDENTITIES

    last = previous.get("offlineEventBox", {}).get("last", {})
    operation = last.get("response", {}).get("operation")
    if not operation or str(operation["id"]) in previous.get(
        "acknowledgedOperations", {}
    ):
        return
    bid = last["request"]["eventBoxId"]
    box = next(r for r in previous["tables"]["UserEventBox"] if r["eventBoxId"] == bid)
    sid = box["currentStepId"]
    item_id = draw_definitions()[0][bid]["item"]
    identities = {
        "UserEventItem": ("eventItemId", item_id),
        "UserEventBox": ("eventBoxId", bid),
        "UserEventBoxStep": ("eventBoxStepId", sid),
        "UserEventBoxContent": ("eventBoxStepId", sid),
    }
    for name, (field, identity) in identities.items():
        old = previous["tables"].get(name, [])
        reserved = [copy.deepcopy(r) for r in old if r[field] == identity]
        rows = [
            r for r in state["tables"].get(name, []) if r[field] != identity
        ] + reserved
        # Preserve the original row order to match native token serialization.
        by_id = {tuple(r[k] for k in TABLE_IDENTITIES[name]): r for r in rows}
        keys = [
            tuple(r[k] for k in TABLE_IDENTITIES[name])
            for r in state["tables"].get(name, [])
        ]
        keys += [key for key in by_id if key not in keys]
        rows = [by_id[k] for k in keys if k in by_id]
        state["tables"][name] = rows
        state["tokens"][name] = hashlib.md5(pack(rows)).hexdigest()
