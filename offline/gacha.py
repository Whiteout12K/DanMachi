"""Offline Gacha support using the original retained master data and ZIP art."""

# Reading guide: Draw service: in-memory master overlays come first, followed by banner
# state, atomic draws and Details HTML.
# Editing notes: Selection reserves payment and a native grant together. Retried
# requests must return the reserved operation; preserve original pools, ticket IDs and
# draw counts.
# Checks: tools/maintain.py test gacha.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools, struct, zlib, subprocess
import tutorial_banner


# Original binary master encoding
def encode(data, key):
    """Encode a scalar/table payload with the retained master format and key."""
    n = (len(data) + 3) // 4
    v = list(struct.unpack("<" + "I" * n, data.ljust(n * 4, b"\0"))) + [len(data)]
    n = len(v)
    z = v[-1]
    s = 0
    for _ in range(6 + 52 // n):
        s = (s + 0x9E3779B9) & 0xFFFFFFFF
        e = (s >> 2) & 3
        for p in range(n - 1):
            y = v[p + 1]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ (
                (s ^ y) + (key[(p & 3) ^ e] ^ z)
            )
            v[p] = (v[p] + mx) & 0xFFFFFFFF
            z = v[p]
        y = v[0]
        p = n - 1
        mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ (
            (s ^ y) + (key[(p & 3) ^ e] ^ z)
        )
        v[p] = (v[p] + mx) & 0xFFFFFFFF
        z = v[p]
    return struct.pack("<" + "I" * n, *v)


@functools.lru_cache(maxsize=1)
def master_asset():
    """
    Patch native banner dates and ticket button compatibility in memory, then
    re-encrypt.
    """
    import rebuild_master as m
    from asset_store import MemoryAsset

    b = bytearray(m.table("lottery"))
    state_path = Path(__file__).resolve().parents[1] / "state/offline/player-state.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    epoch = state.get("offlineGacha", {}).get("epochDay", int(time.time() // 86400))
    from gacha_rotation import month_windows, month_of

    windows = month_windows(month_of(SESSION_TIME))
    enabled = set(windows)
    if tutorial_banner.available(state):
        enabled.add(tutorial_banner.BANNER_ID)
    start = max(0, int(SESSION_TIME) - 86400)
    end = int(SESSION_TIME) + 365 * 86400
    for t in m.rows(b):
        ff = m.fields(b, t)
        lid = int.from_bytes(
            m.decode(bytes(b[ff[0] : ff[0] + 8])), "little", signed=True
        )
        active_start, active_end = windows.get(lid, (start, end))
        for i, value in (
            (4, active_start if lid in enabled else end),
            (5, active_end if lid in enabled else 1),
        ):
            if ff[i]:
                b[ff[i] : ff[i] + 12] = encode(struct.pack("<q", value), m.INNER_KEY)
        # Historical paid daily discounts require the retired billing service.
        # Hide only that optional button; normal archived draws remain available.
        if ff[9]:
            b[ff[9] : ff[9] + 8] = encode(bytes(4), m.INNER_KEY)
        # Retired per-account ticket limits must not strand later tickets.
        for currency_col, limit_col in ((21, 24), (31, 34)):
            if (
                ff[currency_col]
                and m.decode(bytes(b[ff[currency_col] : ff[currency_col] + 8]))
                == b"\x02"
            ):
                if ff[limit_col]:
                    b[ff[limit_col] : ff[limit_col] + 8] = encode(bytes(4), m.INNER_KEY)
        for i in (21, 31):
            if ff[i] and m.decode(bytes(b[ff[i] : ff[i] + 8])) == b"\x03":
                b[ff[i] : ff[i] + 8] = encode(b"\x01", m.INNER_KEY)
    data = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-aes-256-cbc",
            "-K",
            m.AES_KEY.hex(),
            "-iv",
            m.IV.hex(),
        ],
        input=zlib.compress(b),
        capture_output=True,
        check=True,
    ).stdout
    m.decode.cache_clear()
    return MemoryAsset(data)


@functools.lru_cache(maxsize=1)
def scratch_asset():
    # Retired scratch prize/weight services are not present in the folder.
    # Retain associations for existing UserScratch rows, but no playable button
    # attaches a new promotion. Removing associations breaks native initialization.
    """Disable new retired scratch promotions while preserving saved associations."""
    import rebuild_master as m
    from asset_store import MemoryAsset

    b = bytearray(m.table("lotteryScratch"))
    for t in m.rows(b):
        f = m.fields(b, t)[2]
        if f:
            b[f : f + 8] = encode(bytes(4), m.INNER_KEY)
    data = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-aes-256-cbc",
            "-K",
            m.AES_KEY.hex(),
            "-iv",
            m.IV.hex(),
        ],
        input=zlib.compress(b),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(data)


import json, gzip, copy, hashlib, time, secrets, math
from pathlib import Path
from save_store import pack, copy_state

SESSION_TIME = time.time()


# Retained catalog and session availability
@functools.lru_cache(maxsize=1)
def definitions():
    """Expand compact original pools and apply offline ticket access rules in memory."""
    with gzip.open(Path(__file__).with_name("gacha-catalog.json.gz"), "rt") as f:
        data = json.load(f)
    if data.get("version") == 2:
        members = data.pop("members")
        pools = [[members[i] for i in pool] for pool in data.pop("pools")]
        data["groups"] = {k: pools[index] for k, index in data["groups"].items()}
    # Use the same English offer names as the native master overlay.
    from english_presentation import display_name

    for banner in data["banners"]:
        banner["name"] = display_name("lottery", banner["id"], banner["name"])
    # Offline ticket access is repeatable and does not expire while owned.
    data["ticketLifetimes"] = {key: 0 for key in data["ticketLifetimes"]}
    for banner in data["banners"]:
        for button in banner["buttons"]:
            if button["currencyType"] == 2:
                button["limit"] = 0
    return data


def active_banners(epoch_day, now=None, progress=None):
    """Return the calendar-selected offers, using session time unless supplied."""
    from gacha_rotation import active

    return active(epoch_day, SESSION_TIME if now is None else now, progress)


def session_banners(save, state=None):
    # The client caches master data, so provide every dated offer for this
    # calendar month now. Native dates control visibility on Gacha reentry.
    """Cache all offers needed by this native session calendar month."""
    if not hasattr(save, "gachaBanners"):
        from gacha_rotation import month_windows, month_of

        save.gachaWindows = month_windows(month_of(SESSION_TIME))
        save.gachaBanners = [
            b for b in definitions()["banners"] if b["id"] in save.gachaWindows
        ]
    return save.gachaBanners


def lottery_row(user, lid, buttons=None):
    """
    Create the native default progress row for one offer without consuming currency.
    """
    return {
        "userId": user,
        "lotteryId": lid,
        "buttons": buttons
        or [
            {
                "buttonType": i,
                "count": 0,
                "lastPickedAt": 0,
                "loopCount": 0,
                "currentStepIndex": 1,
            }
            for i in (1, 2, 3)
        ],
        "isNew": True,
        "selectedPcId1": 0,
        "selectedPcId2": 0,
        "selectedPcId3": 0,
    }


def canonical(row):
    """Restore native lottery field order so synchronization hashes stay compatible."""
    value = {
        k: row[k]
        for k in (
            "userId",
            "lotteryId",
            "buttons",
            "isNew",
            "selectedPcId1",
            "selectedPcId2",
            "selectedPcId3",
        )
    }
    value["buttons"] = [
        {
            k: b[k]
            for k in (
                "buttonType",
                "count",
                "lastPickedAt",
                "loopCount",
                "currentStepIndex",
            )
        }
        for b in row["buttons"]
    ]
    return value


# Native offer progress and reserved operations
def prepare(save):
    """
    Initialize available offer progress and reconcile authoritative reserved draw
    counts.
    """
    with save.lock:
        if not save.state["tables"].get("UserInfo"):
            return
        state = copy_state(save.state, ("UserLottery",), ("offlineGacha",))
        g = state.setdefault(
            "offlineGacha",
            {"epochDay": int(time.time() // 86400), "sequence": 0, "progress": {}},
        )
        previous = {r["lotteryId"]: r for r in state["tables"].get("UserLottery", [])}
        from gacha_rotation import cycle_start

        for banner in definitions()["banners"]:
            row = g["progress"].get(str(banner["id"]), previous.get(banner["id"]))
            if not row:
                continue
            start = cycle_start(banner, time.time())
            for button in row["buttons"]:
                variants = [
                    v
                    for v in banner["buttons"]
                    if v["buttonType"] == button["buttonType"]
                ]
                free = any(v["cost"] == 0 for v in variants)
                daily = any(v.get("dailyReset") for v in variants) and not free
                returned = free and button["lastPickedAt"] < start
                if returned or (
                    daily
                    and int((time.time() + 32400) // 86400)
                    > int((button["lastPickedAt"] + 32400) // 86400)
                ):
                    button["count"] = 0
                    button["currentStepIndex"] = 1
        # Draw reservations are authoritative. A delayed client push must not
        # replace their consumed count with an older menu snapshot.
        rows = [
            canonical(
                g["progress"].get(
                    str(b["id"]),
                    previous.get(
                        b["id"],
                        lottery_row(state["tables"]["UserInfo"][0]["userId"], b["id"]),
                    ),
                )
            )
            for b in session_banners(save, state)
        ]
        if tutorial_banner.available(state):
            rows.append(
                canonical(
                    previous.get(
                        tutorial_banner.BANNER_ID,
                        lottery_row(
                            state["tables"]["UserInfo"][0]["userId"],
                            tutorial_banner.BANNER_ID,
                        ),
                    )
                )
            )
        state["tables"]["UserLottery"] = rows
        state["tokens"]["UserLottery"] = hashlib.md5(pack(rows)).hexdigest()
        # Old acknowledgments are unnecessary once the last Gacha grant is committed.
        last = g.get("lastDraw", {})
        keep = str(last.get("response", {}).get("operation", {}).get("id", 0))
        state["acknowledgedOperations"] = {
            k: v
            for k, v in state.get("acknowledgedOperations", {}).items()
            if not (400000001 <= int(k) <= 499999999) or k == keep
        }
        if state != save.state:
            save._write(state)


def pending(save):
    """Return the reserved native draw operation until the client acknowledges it."""
    with save.lock:
        response = (
            save.state.get("offlineGacha", {}).get("lastDraw", {}).get("response", {})
        )
        operation = response.get("operation")
        return (
            copy.deepcopy(operation)
            if operation
            and str(operation["id"]) not in save.state.get("acknowledgedOperations", {})
            else None
        )


# Atomic payment, pool selection and native grant reservation
def draw(save, request, key):
    """Reserve one draw atomically; client operations create original unit stats."""
    prepare(save)
    with save.lock:
        state = copy.deepcopy(save.state)
        g = state["offlineGacha"]
        last = g.get("lastDraw")
        if last and last["key"] == key:
            return copy.deepcopy(last["response"])
        if pending(save):
            raise ValueError("Previous Gacha grant is still pending")
        lid = request.get("lotteryId")
        typ = request.get("buttonIndex")
        if type(lid) is not int or type(typ) is not int:
            raise ValueError("Invalid Gacha identity")
        banner = next((b for b in session_banners(save) if b["id"] == lid), None)
        if not banner:
            raise ValueError("Gacha banner is not in the current offline rotation")
        window = getattr(save, "gachaWindows", {}).get(lid)
        if window and not window[0] <= time.time() <= window[1]:
            raise ValueError("Gacha banner is outside its scheduled dates")
        row = next(r for r in state["tables"]["UserLottery"] if r["lotteryId"] == lid)
        button = next((b for b in row["buttons"] if b["buttonType"] == typ), None)
        choices = [b for b in banner["buttons"] if b["buttonType"] == typ]
        definition = (
            next(
                (
                    b
                    for b in choices
                    if b.get("step", button["currentStepIndex"])
                    == button["currentStepIndex"]
                ),
                None,
            )
            if button
            else None
        )
        if not definition:
            raise ValueError("Unsupported Gacha button or completed steps")
        if (
            request.get("pickCount") != definition["count"]
            or request.get("consumeAmount") != definition["cost"]
        ):
            raise ValueError("Gacha cost or count differs from original master data")
        if definition.get("limit", 0) and button["count"] >= definition["limit"]:
            # A stale results-screen button may send a new request ID. Replay
            # the committed response, keeping its operation identity so the
            # native client cannot grant/charge again.
            previous = last.get("response", {}) if last else {}
            previous_rows = previous.get("UserLottery", [])
            last_banner = (
                last.get(
                    "bannerId", previous_rows[0]["lotteryId"] if previous_rows else None
                )
                if last
                else None
            )
            last_button = last.get("buttonType") if last else None
            if last_button is None and previous_rows:
                used = [
                    b
                    for b in previous_rows[0]["buttons"]
                    if b.get("lastPickedAt", 0) > 0
                ]
                latest = max((b["lastPickedAt"] for b in used), default=0)
                candidates = [
                    b["buttonType"] for b in used if b["lastPickedAt"] == latest
                ]
                if len(candidates) == 1:
                    last_button = candidates[0]
            if last_banner == lid and last_button == typ:
                replay = copy.deepcopy(previous)
                if "UserLottery" not in replay.get("data", {}):
                    replay.setdefault("data", {})["UserLottery"] = copy.deepcopy(
                        state["tables"]["UserLottery"]
                    )
                    replay.setdefault("dataTokens", {})["UserLottery"] = state[
                        "tokens"
                    ]["UserLottery"]
                return replay
            raise ValueError("Gacha draw limit reached")
        if request.get("progressCount") != button["count"]:
            raise ValueError("Stale Gacha progress")
        cost = definition["cost"]
        currency = definition["currencyType"]
        ticket = None
        if currency == 1 and cost > 0:
            gem = next(
                (
                    r
                    for r in state["tables"].get("UserCurrency", [])
                    if r["currencyId"] == 205000001
                ),
                None,
            )
            available = gem.get("cumulativeAmount", 0) if gem else 0
            if available - state.get("localIrisSpent", 0) < cost:
                raise ValueError("Not enough earned Iris")
            state["localIrisSpent"] = state.get("localIrisSpent", 0) + cost
        elif currency == 2 and cost > 0:
            ticket = next(
                (
                    r
                    for r in state["tables"].get("UserGachaTicket", [])
                    if r["gachaTicketId"] == definition["ticketId"]
                ),
                None,
            )
            lifetime = definitions()["ticketLifetimes"].get(
                str(definition["ticketId"]), 0
            )
            dates = (
                sorted(
                    (
                        v
                        for v in ticket.get("dateList", [])
                        if not lifetime or v["aquiredAt"] + lifetime > time.time()
                    ),
                    key=lambda v: v["aquiredAt"],
                )
                if ticket
                else []
            )
            if len(dates) < cost:
                raise ValueError("Not enough unexpired Gacha tickets")
            ticket["dateList"] = dates[cost:]
            state["tokens"]["UserGachaTicket"] = hashlib.md5(
                pack(state["tables"]["UserGachaTicket"])
            ).hexdigest()
        groups = definitions()["groups"]
        fixed = definition["fixedCount"]
        pool = groups.get(str(definition["group"]), [])
        ordinal = button["count"] + 1
        if banner.get("cycle"):
            ordinal = (ordinal - 1) % banner["cycle"] + 1
        milestone = (
            next(
                (r for r in banner.get("milestones", []) if r["count"] == ordinal), None
            )
            if definition["count"] > 1
            else None
        )
        if milestone:
            fixed = max(1, fixed)
            definition = {**definition, "fixedGroup": milestone["group"]}
        picked = [secrets.choice(pool) for _ in range(definition["count"] - fixed)]
        if fixed:
            fixed_pool = groups[str(definition["fixedGroup"])]
            writable = next(
                (
                    r
                    for r in state["tables"].get("UserWritableLotteryData", [])
                    if r["lotteryId"] == lid
                ),
                row,
            )
            selected = [writable.get("selectedPcId" + str(i), 0) for i in (1, 2, 3)]
            selected_pool = [pc for pc in fixed_pool if pc in selected]
            picked.extend(
                secrets.choice(selected_pool or fixed_pool) for _ in range(fixed)
            )
        owned = {r["pcId"] for r in state["tables"].get("UserPC", [])}
        results = []
        new = []
        bonds = {}
        for pc in picked:
            first = pc not in owned
            results.append({"pcId": pc, "isFirst": first})
            if first:
                new.append({"pcId": pc})
                owned.add(pc)
            else:
                bond = definitions()["bonds"].get(str(pc))
                if not bond:
                    raise ValueError("Original duplicate bond definition is missing")
                bonds[bond] = bonds.get(bond, 0) + 1
        balances = {
            r["limitBreakItemId"]: r
            for r in state["tables"].get("UserLimitBreakItem", [])
        }
        targets = {}
        for item_id, increment in bonds.items():
            previous = balances.get(item_id, {})
            targets[str(item_id)] = {
                "amount": previous.get("amount", 0) + increment,
                "cumulativeAmount": previous.get(
                    "cumulativeAmount", previous.get("amount", 0)
                )
                + increment,
            }
        # Operation 1001 replaces this item's balance rather than adding it.
        items = [
            {
                "limitBreakItemId": k,
                "amount": targets[str(k)]["amount"],
                "cumulativeAmount": targets[str(k)]["cumulativeAmount"],
            }
            for k in bonds
        ]
        button["count"] += 1
        button["lastPickedAt"] = int(time.time())
        if "step" in definition:
            button["currentStepIndex"] += 1
        g["progress"][str(lid)] = canonical(row)
        g["sequence"] += 1
        sequence = 400000000 + g["sequence"]
        response = {
            "code": 0,
            "lotteryPCs": results,
            "UserLottery": [copy.deepcopy(row)],
            "UserScratch": [],
            "UserCommunicationCharacter": [],
            "UserHeroSublimatePCs": [],
            "UserPC": new,
            "UserLimitBreakItem": items,
            "data": {},
            "dataTokens": {},
            "operations": [],
            "dones": [],
            "operation": {
                "id": sequence,
                "type": 1001,
                "signature": sequence,
                "token": "",
                "parameters": {
                    "UserPC": new,
                    "UserLimitBreakItem": items,
                    "UserHeroSublimatePCs": [],
                    "UserCommunicationCharacter": [],
                },
            },
        }
        state["tokens"]["UserLottery"] = hashlib.md5(
            pack(state["tables"]["UserLottery"])
        ).hexdigest()
        response["dataTokens"]["UserLottery"] = state["tokens"]["UserLottery"]
        response["data"] = {
            k: copy.deepcopy(response[k])
            for k in (
                "lotteryPCs",
                "UserScratch",
                "UserCommunicationCharacter",
                "UserHeroSublimatePCs",
            )
        }
        # Publish the complete authoritative table through the same update
        # mechanism used by push responses, so results can disable Repeat.
        response["data"]["UserLottery"] = copy.deepcopy(state["tables"]["UserLottery"])
        # Native callbacks receive operation parameters after the grant commits.
        response["operation"]["parameters"]["lotteryPCs"] = copy.deepcopy(results)
        response["operation"]["parameters"]["UserLottery"] = copy.deepcopy(
            response["UserLottery"]
        )
        if ticket:
            response["userGachaTicket"] = copy.deepcopy(ticket)
            response["data"]["UserGachaTicket"] = [copy.deepcopy(ticket)]
            response["dataTokens"]["UserGachaTicket"] = state["tokens"][
                "UserGachaTicket"
            ]
            response["operation"]["parameters"]["userGachaTicket"] = copy.deepcopy(
                ticket
            )
        g["lastDraw"] = {
            "key": key,
            "bannerId": lid,
            "buttonType": typ,
            "bondTargets": targets,
            "response": response,
        }
        save._write(state)
        return copy.deepcopy(response)


# Native display compatibility and readable offer details
@functools.lru_cache(maxsize=1)
def missing_text_layout():
    # Rebuild the absent 263x62 label-only component expected by the APK.
    # All label artwork remains in the original archives.
    """Provide the missing retained banner text layout expected by native UI."""
    from asset_store import MemoryAsset

    labels = []
    for tag in range(1, 14):
        labels.append(
            {
                "tag": tag,
                "name": "gachaText" + str(tag),
                "class": "Sprite",
                "z": tag,
                "opacity": 255,
                "anchor_point": {"x": 0.5, "y": 0.5},
                "ll": "LL_SPRITE",
                "llClass": "cocos2d::Sprite",
                "image": str(tag) + ".png",
                "position": {"x": 131.5, "y": 31},
                "childs": [],
            }
        )
    return MemoryAsset(
        json.dumps(
            {
                "root": {
                    "class": "Node",
                    "tag": 0,
                    "z": 0,
                    "opacity": 255,
                    "anchor_point": {"x": 0, "y": 0},
                    "position": {"x": 0, "y": 0},
                    "size": {"width": 263, "height": 62},
                    "directory": "gacha_top_move_parts_text",
                    "childs": labels,
                }
            },
            separators=(",", ":"),
        ).encode()
    )


@functools.lru_cache(maxsize=1)
def unit_metadata():
    """Read original English unit names and rarity from the retained PC master."""
    import rebuild_master as m

    from english_presentation import display_name

    b = m.table("pc")
    wanted = {pc for pool in definitions()["groups"].values() for pc in pool}
    units = {}
    for row in m.rows(b):
        pc = m.scalar(b, row, 0)
        if pc in wanted:
            units[pc] = {
                "name": m.text(b, row, 2),
                "title": display_name("pc", pc, m.text(b, row, 1), 1),
                "rarity": m.scalar(b, row, 46),
            }
    if any(u["rarity"] not in (1, 2, 3, 4) for u in units.values()):
        raise ValueError("Invalid original unit rarity")
    if wanted - set(units):
        raise ValueError("A Gacha unit is missing from the original PC master")
    m.decode.cache_clear()
    return units


def details_html(lottery_id=None, state=None):
    """Explain the selected offer and its original pool in a local Details page."""
    from html import escape
    from collections import Counter

    banner = next((b for b in definitions()["banners"] if b["id"] == lottery_id), None)
    from web_pages import HEAD

    header = HEAD
    if not banner:
        return (
            header
            + "<h2>Gacha Details</h2><p>No matching archived banner was selected.</p>"
        )
    parts = [
        header,
        "<h2>" + escape(banner["name"]) + "</h2>",
        "<p><b>Offline draw rates.</b> Unit names, rarities and eligible pools come from the retained original game master data. Original server probability weights are not present. The percentages below describe the actual offline uniform selection within each pool, not historical live-service odds.</p>",
        "<p>Current-event banners follow the monthly event schedule, alongside ten Iris/free banners: six regular, two rotating daily, and two anniversary banners rotating daily. All matching ticket banners are permanently available when their tickets are held, including special and event tickets. Owned tickets do not expire in this offline game, and ticket draws can be repeated while tickets remain. Leave and reenter Gacha to refresh daily offers. Reopen the game when the calendar month changes. Free offers reset when returning in a later monthly or daily rotation; paid daily-marked draws retain their daily reset (JST). Historical dates printed in artwork are unchanged.</p>",
    ]
    units = unit_metadata()
    groups = definitions()["groups"]
    shown = {}

    def pool_section(group, label):
        pool = groups.get(str(group), [])
        if not pool:
            return "<p>" + escape(label) + ": no picks use this pool.</p>"
        identity = tuple(pool)
        if identity in shown:
            return (
                "<p>"
                + escape(label)
                + ": same eligible units and rates as "
                + escape(shown[identity])
                + ".</p>"
            )
        shown[identity] = label
        counts = Counter(units[pc]["rarity"] for pc in pool)
        html = (
            "<h3>"
            + escape(label)
            + "</h3><table><tr><th>Rarity</th><th>Units</th><th>Rate per pick</th></tr>"
        )
        for rarity in sorted(set(range(1, 5)) | set(counts)):
            html += f"<tr><td>{rarity}★</td><td>{counts[rarity]}</td><td>{100*counts[rarity]/len(pool):.4f}%</td></tr>"
        html += (
            "</table><details><summary>Eligible units ("
            + str(len(pool))
            + ")</summary><table><tr><th>Unit</th><th>Rarity</th><th>Rate per pick</th></tr>"
        )
        for pc in sorted(
            pool,
            key=lambda pc: (
                -units[pc]["rarity"],
                units[pc]["name"],
                units[pc]["title"],
                pc,
            ),
        ):
            u = units[pc]
            name = "[" + u["title"] + "] " + u["name"]
            html += f'<tr><td>{escape(name)}<br><small>ID {pc}</small></td><td>{u["rarity"]}★</td><td>{100/len(pool):.4f}%</td></tr>'
        return html + "</table></details>"

    for v in banner["buttons"]:
        label = (
            ("Step " + str(v["step"]))
            if v.get("step")
            else str(v["count"]) + "-unit draw"
        )
        parts.append(
            "<h3>"
            + escape(label)
            + "</h3><p>Cost: "
            + str(v["cost"])
            + (" ticket(s)" if v["currencyType"] == 2 else " earned Iris")
            + ". "
        )
        if v.get("limit"):
            parts.append("Limit: " + str(v["limit"]) + " draw(s). ")
        parts.append(
            str(v["count"] - v["fixedCount"])
            + " normal pick(s), "
            + str(v["fixedCount"])
            + " guaranteed pick(s).</p>"
        )
        if v["count"] > v["fixedCount"]:
            parts.append(pool_section(v["group"], "Normal pool"))
        if v["fixedCount"]:
            pool = groups.get(str(v["fixedGroup"]), [])
            selected = []
            if state:
                fallback = next(
                    (
                        r
                        for r in state.get("tables", {}).get("UserLottery", [])
                        if r["lotteryId"] == lottery_id
                    ),
                    {},
                )
                row = next(
                    (
                        r
                        for r in state.get("tables", {}).get(
                            "UserWritableLotteryData", []
                        )
                        if r["lotteryId"] == lottery_id
                    ),
                    fallback,
                )
                selected = [row.get("selectedPcId" + str(i), 0) for i in (1, 2, 3)]
                selected = [pc for pc in pool if pc in selected]
            if selected:
                counts = Counter(units[pc]["rarity"] for pc in selected)
                parts.append(
                    "<p>Selected guaranteed rarity rates: "
                    + ", ".join(
                        f"{r}★ {100*counts[r]/len(selected):.4f}%" for r in range(1, 5)
                    )
                    + ".</p>"
                )
                parts.append(
                    "<p>Your selected eligible units override the guaranteed pool: "
                    + ", ".join(
                        escape("[" + units[pc]["title"] + "] " + units[pc]["name"])
                        + " ("
                        + str(units[pc]["rarity"])
                        + "★, "
                        + f"{100/len(selected):.4f}%"
                        + ")"
                        for pc in selected
                    )
                    + ".</p>"
                )
            else:
                parts.append(pool_section(v["fixedGroup"], "Guaranteed pool"))
    for milestone in banner.get("milestones", []):
        parts.append(
            "<h3>Multi-draw number "
            + str(milestone["count"])
            + "</h3><p>This milestone replaces the guaranteed pool.</p>"
        )
        parts.append(
            pool_section(
                milestone["group"],
                "Milestone " + str(milestone["count"]) + " guaranteed pool",
            )
        )
    parts.append(
        "<p>Rates are for individual picks; a guaranteed final pick has its own pool. Duplicate units grant their original bonds. Purchases, historical daily paid discounts and scratch bonuses are unavailable offline.</p><p>Close this page to return to the banner.</p>"
    )
    return "".join(parts)
