"""Reconstruct a compact Gacha catalog from retained APK/master/ZIP files."""

# Reading guide: Catalog builder: decode original tables and compact repeated unit pools
# into gacha-catalog.json.gz.
# Editing notes: This is a regeneration tool, not the live draw handler. Changing source
# logic requires rebuilding the catalog and checking retained pool/count invariants.
# Checks: tools/maintain.py test gacha.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import sys, json, gzip, collections, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "offline"))
import rebuild_master as m
from zip_reader import catalog


def value(b, t, i):
    """Decode a retained master scalar using its actual encoded field width."""
    f = m.fields(b, t)[i]
    if not f:
        return 0
    for n in (8, 12):
        try:
            return int.from_bytes(m.decode(b[f : f + n]), "little", signed=True)
        except ValueError:
            pass
    raise ValueError("Unknown scalar width")


def compact_catalog(data):
    """Store shared pools and member indices; expand only in process memory."""
    members = sorted({pc for pool in data["groups"].values() for pc in pool})
    member_index = {pc: i for i, pc in enumerate(members)}
    pools = []
    indices = {}
    groups = {}
    for key, pool in sorted(data["groups"].items()):
        identity = tuple(pool)
        if identity not in indices:
            indices[identity] = len(pools)
            pools.append([member_index[pc] for pc in pool])
        groups[key] = indices[identity]
    return {
        **data,
        "version": 2,
        "groups": groups,
        "pools": pools,
        "members": members,
        "bonds": {
            key: value
            for key, value in data["bonds"].items()
            if int(key) in member_index
        },
    }


def build():
    """Regenerate the compact catalog from original lottery, ticket and unit masters."""
    paths = catalog()
    groups = collections.defaultdict(set)
    from asset_store import records

    backgrounds = {p for p in records() if "/lottery/background/" in p}
    backgrounds.update("1/" + p.split("/", 1)[1] for p in tuple(backgrounds))
    b = m.table("lotteryCharacter")
    for t in m.rows(b):
        groups[value(b, t, 1)].add(value(b, t, 2))
    groups = {str(k): sorted(v) for k, v in groups.items()}
    b = m.table("lotteryStepUpStep")
    steps = collections.defaultdict(list)
    for t in m.rows(b):
        row = [value(b, t, i) for i in range(9)]
        steps[str(row[1])].append(
            {
                "group": row[2],
                "fixedGroup": row[3],
                "buttonType": row[4],
                "step": row[5],
                "cost": row[6],
                "count": row[7],
                "fixedCount": row[8],
            }
        )
    for v in steps.values():
        v.sort(key=lambda r: r["step"])
    b = m.table("limitBreakItem")
    bond_aliases = {m.text(b, t, 1): value(b, t, 0) for t in m.rows(b)}
    b = m.table("pc")
    bonds = {
        str(value(b, t, 0)): bond_aliases.get(
            m.text(b, t, 8).replace("character.", "limit_break_item.")
        )
        for t in m.rows(b)
    }
    b = m.table("lotteryStep")
    milestones = collections.defaultdict(list)
    for t in m.rows(b):
        r = [value(b, t, i) for i in range(5)]
        if r[3] and str(r[3]) in groups:
            milestones[r[1]].append({"count": r[2], "group": r[3]})
    b = m.table("lottery")
    banners = []
    for t in m.rows(b):
        row = [
            value(b, t, i) if i != 2 else m.text(b, t, i)
            for i in range(len(m.fields(b, t)))
        ]
        lid = row[0]
        ticket_offer = any(row[col] and row[col + 1] == 2 for col in (20, 30))
        if row[1] or (
            not ticket_offer
            and f"1/files/lottery/background/{lid}.png" not in backgrounds
        ):
            continue
        buttons = []
        for typ, col in ((2, 20), (3, 30)):
            if row[col] and row[col + 1] in (1, 2, 3) and row[col + 2] >= 0:
                buttons.append(
                    {
                        "buttonType": typ,
                        "count": row[col],
                        "cost": row[col + 2],
                        "currencyType": 1 if row[col + 1] == 3 else row[col + 1],
                        "dailyReset": bool(row[44 if typ == 2 else 45]),
                        "limit": row[col + 4],
                        "ticketId": row[col + 3],
                        "group": row[7],
                        "fixedGroup": row[col + 5],
                        "fixedCount": (
                            0
                            if row[col + 1] == 2 and not row[col + 5]
                            else row[col + 6]
                        ),
                    }
                )
        for typ, group_col in ((2, 42), (3, 43)):
            stepup = steps.get(str(row[group_col]), [])
            if stepup:
                buttons = [v for v in buttons if v["buttonType"] != typ] + [
                    {**s, "buttonType": typ, "currencyType": 1, "ticketId": 0}
                    for s in stepup
                ]
        if not buttons or any(
            (x["count"] > x["fixedCount"] and not groups.get(str(x["group"])))
            or (x["fixedCount"] and not groups.get(str(x["fixedGroup"])))
            for x in buttons
        ):
            continue
        banners.append(
            {
                "id": lid,
                "name": row[2],
                "start": row[4],
                "cycle": 0,
                "milestones": milestones[lid],
                "buttons": buttons,
            }
        )
    banners.sort(key=lambda r: (r["start"], r["id"]))
    used = {
        str(step["group"]) for banner in banners for step in banner["milestones"]
    } | {
        str(x[k])
        for b in banners
        for x in b["buttons"]
        for k in ("group", "fixedGroup")
        if x[k]
    }
    tickets_used = {
        v["ticketId"]
        for banner in banners
        for v in banner["buttons"]
        if v["currencyType"] == 2
    }
    b = m.table("gachaTicket")
    ticket_lifetimes = {
        str(value(b, t, 0)): value(b, t, 4)
        for t in m.rows(b)
        if value(b, t, 0) in tickets_used
    }
    result = {
        "ticketLifetimes": ticket_lifetimes,
        "version": 1,
        "rotation": "Ten Iris/free offers plus current events and permanent matching ticket choices",
        "odds": "Uniform among original stored members of each pool; original server probability weights are absent. Original fixed-pick pools/counts retained.",
        "banners": banners,
        "groups": {k: groups[k] for k in used},
        "bonds": bonds,
        "originalBannerRecords": 2236,
    }
    result["ticketArtFallbacks"] = {
        str(b["id"]): (
            171002225
            if b["buttons"][0]["fixedCount"] and b["buttons"][0]["count"] > 1
            else 171002224 if b["buttons"][0]["count"] > 1 else 171002222
        )
        for b in banners
        if f"1/files/lottery/background/{b['id']}.png" not in backgrounds
    }
    p = ROOT / "offline/gacha-catalog.json.gz"
    p.write_bytes(
        gzip.compress(
            json.dumps(compact_catalog(result), separators=(",", ":")).encode(),
            compresslevel=9,
            mtime=0,
        )
    )
    print(
        "Retained banners:",
        len(banners),
        "groups:",
        len(used),
        "catalog bytes:",
        p.stat().st_size,
    )
    m.decode.cache_clear()


if __name__ == "__main__":
    build()
