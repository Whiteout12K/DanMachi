"""Folder-local Familia state; remote accounts are never fabricated."""

# Reading guide: Local Familia protocol: build the current player/member response and
# handle supported menu actions.
# Editing notes: There are no remote members or rankings to synthesize. Persist local
# changes through the SaveStore lock.
# Checks: offline/test_familia.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy, hashlib, json, time
from save_store import pack

ACTIONS = tuple(
    "familia/" + a
    for a in (
        "mystatus",
        "create",
        "get",
        "search/random",
        "search/name",
        "search/option",
        "invited/list",
        "invite/search",
        "join/list/sent",
        "join/list/recieved",
        "join/cancel",
        "join/send",
        "invited/accept",
        "manage/change/info",
        "manage/change/god",
        "leave",
        "break",
        "msg_board/feed",
        "msg_board/feed_by_no",
        "msg_board/send",
        "skill/get",
        "skill/growth",
        "achievement/get",
        "opening_event",
        "first_reward/receive",
        "union/setting",
        "donate/item",
        "donate/valis",
        "shop/item/set",
        "shop/item/buy",
        "invite/send",
        "join/approve",
        "kick",
        "manage/appoint_submaster",
        "manage/dismessed_submaster",
        "manage/change_master",
    )
)


def reply(**fields):
    """Build the standard local Familia response envelope."""
    return {
        "code": 0,
        "result": 0,
        "data": {},
        "dataTokens": {},
        "operations": [],
        "dones": [],
        **fields,
    }


def integer(value, low=0, high=2**63 - 1):
    """Validate a request integer and enforce its allowed range."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid Familia number")
    return value


def text(value, limit):
    """Validate request text length/content and trim surrounding whitespace."""
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("Invalid Familia text")
    return value.strip()


def player(state):
    """Read the local account record used to describe the Familia member."""
    info = state["tables"].get("UserInfo", [])
    if not info:
        raise ValueError("Player is not initialized")
    return info[0]


def member(state, group):
    """Build the current account member record without inventing remote players."""
    info = player(state)
    status = state["tables"].get("UserStatus", [{}])[0]
    units = state["tables"].get("UserPC", [])
    unit = next(
        (u for u in units if u.get("pcId") == group.get("leaderPcId")),
        units[0] if units else {},
    )
    level = info.get("playerStatus", {}).get("level", 1)
    return {
        "userId": info["userId"],
        "rank": level,
        "name": info.get("name", ""),
        "description": state["tables"]
        .get("UserProfile", [{}])[0]
        .get("description", ""),
        "totalStatusPoint": 0,
        "lastLoginedAt": status.get("lastLoginedAt", 0),
        "leaderPc": {
            "pcId": unit.get("pcId", 1011001001),
            "jobRank": 1,
            "level": 1,
            "heroSublimateLevel": unit.get("heroSublimateLevel", 0),
            "isUnlockedHeroSublimate": unit.get("isUnlockedHeroSublimate", False),
        },
        "post": 1,
        "contributionPoint": group.get("memberContributionPoint", 0),
    }


def status_reply(state):
    """Describe the folder-local Familia status expected by native menus."""
    local = state.get("offlineFamilia", {})
    group = local.get("group") if local.get("joined") else None
    if not group:
        return reply(
            status={
                "familiaId": 0,
                "recievedRequest": False,
                "canReceiveFirstReward": False,
            },
            members=[],
        )
    info = copy.deepcopy(group)
    return reply(
        status={
            "familiaId": group["id"],
            "recievedRequest": False,
            "displayApproved": True,
            "joinedAt": local["joinedAt"],
            "canLeave": True,
            "canUnion": False,
            "unionStatus": 0,
            "unionCondition": 0,
            "unionResult": 0,
            "unionWithFamiliaName": "",
            "unionRegisteredAt": 0,
            "unionTimeDuring": 0,
            "canReceiveFirstReward": False,
        },
        familia=info,
        members=[member(state, group)],
    )


def settings(request, existing=None):
    """Validate requested Familia settings and merge them with the existing group."""
    result = copy.deepcopy(existing or {})
    if existing is None:
        result["name"] = text(request.get("name", ""), 30)
        if not result["name"]:
            raise ValueError("Familia name is empty")
    if "description" in request:
        result["description"] = text(request["description"], 500)
    for key in ("godId", "style", "subStyle", "activeTime", "subActiveTime"):
        if key in request:
            result[key] = integer(request[key])
    if "requireApproval" in request:
        if type(request["requireApproval"]) is not bool:
            raise ValueError("Invalid approval setting")
        result["requireApproval"] = request["requireApproval"]
    return result


def handle(save, action, request, key):
    """
    Dispatch supported Familia requests and persist local changes under the save
    lock.
    """
    if action not in ACTIONS:
        raise ValueError("Unsupported Familia action")
    if not isinstance(request, dict):
        raise ValueError("Invalid Familia request")
    with save.lock:
        state = copy.deepcopy(save.state)
        info = player(state)
        local = state.setdefault(
            "offlineFamilia",
            {"joined": False, "messages": [], "sequence": 0, "retries": {}},
        )
        group = local.get("group")
        joined = local.get("joined", False)
        identity = hashlib.sha256(
            (
                action
                + ":"
                + key
                + ":"
                + json.dumps(request, sort_keys=True, separators=(",", ":"))
            ).encode()
        ).hexdigest()
        mutating = action not in READ_ACTIONS
        if mutating and identity in local["retries"]:
            return copy.deepcopy(local["retries"][identity])
        if action == "familia/mystatus":
            return status_reply(state)
        if action in (
            "familia/search/random",
            "familia/search/name",
            "familia/search/option",
        ):
            matches = []
            if group and (
                action != "familia/search/name"
                or text(request.get("name", ""), 30).casefold()
                in group["name"].casefold()
            ):
                matches = [
                    {
                        "familia": copy.deepcopy(group),
                        "master": member(state, group),
                        "memberCount": 1 if joined else 0,
                    }
                ]
            return reply(familias=matches)
        if action in (
            "familia/invited/list",
            "familia/join/list/sent",
            "familia/join/list/recieved",
        ):
            return reply(familias=[], requests=[])
        if action == "familia/invite/search":
            return reply(users=[], players=[], members=[])
        if action == "familia/create":
            if joined:
                return reply(result=1)
            s = settings(request)
            group = {
                "id": 1,
                "name": s["name"],
                "description": s.get("description", ""),
                "godId": s.get("godId", 20000001),
                "style": s.get("style", 21000001),
                "subStyle": s.get("subStyle", 0),
                "activeTime": s.get("activeTime", 22000001),
                "subActiveTime": s.get("subActiveTime", 0),
                "requireApproval": s.get("requireApproval", False),
                "contributionPoint": 0,
                "valis": 0,
                "skillPoint": 0,
                "bgmId": 63200000001,
                "backgroundImageId": 63100000001,
                "unionStatus": 0,
                "familiaSkillIds": [],
                "purchasedProduct": [],
                "memberContributionPoint": 0,
            }
            local.update(
                group=group, joined=True, joinedAt=int(time.time()), messages=[]
            )
            response = status_reply(state)
        elif action in ("familia/join/send", "familia/invited/accept"):
            if joined or not group or request.get("familiaId") != group["id"]:
                return reply(result=1)
            local.update(joined=True, joinedAt=int(time.time()))
            response = status_reply(state)
        elif action == "familia/join/cancel":
            response = reply()
        elif action == "familia/get":
            if not group or request.get("familiaId", group["id"]) != group["id"]:
                return reply(result=1)
            return reply(
                familia=copy.deepcopy(group),
                members=[member(state, group)] if joined else [],
                master=member(state, group),
                memberCount=1 if joined else 0,
            )
        elif not joined:
            return reply(result=1)
        elif "familiaId" in request and request["familiaId"] != group["id"]:
            return reply(result=1)
        elif action in ("familia/manage/change/info", "familia/manage/change/god"):
            group.update(settings(request, group))
            response = status_reply(state)
        elif action in ("familia/leave", "familia/break"):
            local["joined"] = False
            if action == "familia/break":
                local.pop("group", None)
                local["messages"] = []
            response = status_reply(state)
        elif action in ("familia/msg_board/feed", "familia/msg_board/feed_by_no"):
            messages = copy.deepcopy(local["messages"])
            if action.endswith("feed_by_no"):
                no = integer(request.get("no", 0))
                count = integer(request.get("resultCount", 20), 1, 100)
                messages = (
                    [m for m in messages if m["feedNo"] < no]
                    if request.get("cond", 0) == 0 and no
                    else messages
                )
                messages = messages[-count:]
            return reply(messages=messages)
        elif action == "familia/msg_board/send":
            message = request.get("message", "")
            post = integer(request.get("postType", 0), 0, 100)
            if not isinstance(message, (str, dict)):
                raise ValueError("Invalid message")
            encoded = (
                json.dumps(message, separators=(",", ":"))
                if isinstance(message, dict)
                else text(message, 2000)
            )
            if len(encoded) > 2000:
                raise ValueError("Message too long")
            local["sequence"] += 1
            local["messages"].append(
                {
                    "feedNo": local["sequence"],
                    "userId": info["userId"],
                    "userName": info.get("name", ""),
                    "message": encoded,
                    "postType": post,
                    "postedAt": int(time.time()),
                    "expireAt": 4102444800,
                }
            )
            local["messages"] = local["messages"][-100:]
            response = reply(messages=[copy.deepcopy(local["messages"][-1])])
        elif action == "familia/skill/get":
            return reply(
                familiaSkillIds=copy.deepcopy(group["familiaSkillIds"]),
                skillPoint=group["skillPoint"],
            )
        elif action == "familia/achievement/get":
            return reply(achievements=[], records=[])
        elif action == "familia/opening_event":
            response = reply(events=[], familiaEvents=[])
        elif action == "familia/first_reward/receive":
            return reply(result=1)
        else:
            return reply(result=1)
        local["retries"][identity] = copy.deepcopy(response)
        while len(local["retries"]) > 32:
            local["retries"].pop(next(iter(local["retries"])))
        save._write(state)
        return response


READ_ACTIONS = frozenset(
    "familia/" + a
    for a in (
        "mystatus",
        "get",
        "search/random",
        "search/name",
        "search/option",
        "invited/list",
        "invite/search",
        "join/list/sent",
        "join/list/recieved",
        "msg_board/feed",
        "msg_board/feed_by_no",
        "skill/get",
        "achievement/get",
    )
)
