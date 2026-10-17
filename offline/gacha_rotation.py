"""Ten Iris/free offers, current-event banners, and permanent ticket access."""

# Reading guide: Banner calendar: title matching links event offers; active() chooses
# the lineup; month_windows() preloads native dates.
# Editing notes: Ten Iris/free offers are independent of ticket ownership. Current
# events and permanent matching ticket offers are additional. Daily rotation uses UTC
# days.
# Checks: tools/maintain.py test gacha.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import datetime
import functools
import hashlib
import math
import re

FAMILIES = (
    "grand day",
    "argonaut",
    "astrea record",
    "aedes vesta",
    "knights of fianna",
    "orgion saga",
)


def words(text):
    """Normalize title words for matching banners to retained events."""
    text = text.lower().replace("recollections of the wind", "wind recollections")
    tokens = re.findall(r"[a-z]+", text)
    ignored = {
        "gacha",
        "draw",
        "ticket",
        "guaranteed",
        "gtd",
        "paid",
        "free",
        "rerun",
        "first",
        "time",
        "jp",
        "us",
        "asia",
        "europe",
        "japanese",
        "danmemo",
        "danmachi",
        "part",
        "i",
        "ii",
        "iii",
        "iv",
        "the",
        "of",
        "a",
        "in",
        "to",
        "and",
        "is",
    }
    return set(tokens) - ignored


def family(text):
    """Identify an anniversary family from its retained title, if one matches."""
    lowered = text.lower()
    for f in FAMILIES:
        if words(f) <= words(lowered):
            return f
    if "anniv" in lowered:
        match = re.search(r"([1-6])(?:st|nd|rd|th)?\s*(?:year|yr)?\s*anniv", lowered)
        if match:
            return FAMILIES[int(match.group(1)) - 1]
        return "anniversary"
    return None


@functools.lru_cache(maxsize=1)
def links():
    """Match retained banners to original event episodes by family or title words."""
    import gacha
    import rebuild_master as m
    from build_gacha import value
    from guild_events import episode_links

    parents = m.table("adventure")
    event_parents = {
        value(parents, t, 0)
        for t in m.rows(parents)
        if value(parents, t, 2) in (8, 9, 16)
    }
    available = {v[0] for v in episode_links().values() if v[1] in event_parents}
    b = m.table("adventureEpisode")
    episodes = []
    for row in m.rows(b):
        eid = value(b, row, 0)
        if eid in available:
            title = m.text(b, row, 4)
            episodes.append((eid, words(title), family(title)))
    result = {}
    for banner in gacha.definitions()["banners"]:
        name = banner["name"]
        fam = family(name)
        tokens = words(name)
        if fam:
            matched = {eid for eid, w, f in episodes if f == fam}
            result[banner["id"]] = {"family": fam, "episodes": sorted(matched)}
            continue
        candidates = []
        for eid, w, f in episodes:
            overlap = len(tokens & w)
            named_collab = "collab" in name.lower() and bool(
                tokens & w & {"kino", "goblin", "titan", "index"}
            )
            if (overlap >= 2 and overlap / max(1, len(w)) >= 0.6) or named_collab:
                candidates.append((overlap / max(len(tokens), len(w)), eid))
        if candidates:
            best = max(s for s, eid in candidates)
            result[banner["id"]] = {
                "family": None,
                "episodes": sorted(eid for s, eid in candidates if s == best),
            }
    return result


def month_of(timestamp):
    """Convert a UTC timestamp to a continuous month index for rotation."""
    date = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
    return date.year * 12 + date.month - 1


def supplementary_windows(existing, month):
    """Schedule otherwise unassigned retained events into monthly groups."""
    from guild_quests import month_window

    groups = sorted(
        {
            tuple(v["episodes"])
            for v in links().values()
            if not v["family"]
            and v["episodes"]
            and not any(e in existing for e in v["episodes"])
        }
    )
    result = {}
    if groups:
        rounds = math.ceil(len(groups) / 2)
        current = month % rounds
        for index, group in enumerate(groups):
            offset = (index // 2 - current) % rounds
            for eid in group:
                result[eid] = month_window(month + offset)
    return result


# Latest retained standard ticket pools, one banner per ticket type.
TICKET_BANNERS = (171002220, 171002221, 171002222, 171002223, 171002224, 171002225)


@functools.lru_cache(maxsize=1)
def permanent_ticket_ids():
    """Keep all distinct original ticket choices, collapsing superseded copies."""
    import gacha

    banners = gacha.definitions()["banners"]
    standard = {
        v["ticketId"]
        for b in banners
        if b["id"] in TICKET_BANNERS
        for v in b["buttons"]
    }
    choices = {}
    for b in sorted(banners, key=lambda b: (b["start"], b["id"])):
        if not all(v["currencyType"] == 2 for v in b["buttons"]):
            continue
        if any(v["ticketId"] in standard for v in b["buttons"]):
            continue
        signature = tuple(
            tuple(
                v.get(k, 0)
                for k in (
                    "ticketId",
                    "buttonType",
                    "count",
                    "cost",
                    "group",
                    "fixedGroup",
                    "fixedCount",
                )
            )
            for v in b["buttons"]
        )
        signature += (tuple((v["count"], v["group"]) for v in b.get("milestones", [])),)
        choices[signature] = b["id"]
    return (*TICKET_BANNERS, *sorted(choices.values()))


def current_events(timestamp):
    """Return banner IDs linked to events scheduled in the current month."""
    from guild_events import schedule
    from guild_quests import month_window

    window = month_window(month_of(timestamp))
    episodes = {eid for eid, w in schedule().items() if w == window}
    return {
        lid
        for lid, link in links().items()
        if not link["family"] and episodes.intersection(link["episodes"])
    }


def cycle_start(banner, timestamp):
    """Find the current availability/reset boundary for a banner."""
    if banner["id"] in permanent_ticket_ids():
        return 0
    if banner["id"] in current_events(timestamp):
        from guild_quests import month_window

        return month_window(month_of(timestamp))[0]
    return int(timestamp // 86400) * 86400


def consumed(banner, progress, timestamp):
    """Hide a free offer only when its progress belongs to this availability cycle."""
    row = (progress or {}).get(str(banner["id"]), {})
    cutoff = cycle_start(banner, timestamp)
    for v in banner["buttons"]:
        if v["cost"] != 0:
            continue
        for button in row.get("buttons", []):
            if (
                v["buttonType"] != button["buttonType"]
                or button["lastPickedAt"] < cutoff
            ):
                continue
            if v.get("step"):
                if button["currentStepIndex"] > v["step"]:
                    return True
            elif button["count"] > 0:
                return True
    return False


def active(epoch_day, timestamp, progress=None):
    """Combine six regular offers, daily pairs, current events and permanent tickets."""
    import gacha

    banners = gacha.definitions()["banners"]
    by_id = {b["id"]: b for b in banners}
    fixed = [by_id[i] for i in TICKET_BANNERS]
    # Iris offers remain usable without requiring retired event-specific tickets.
    eligible = [
        b
        for b in banners
        if b["id"] not in TICKET_BANNERS
        and any(v["currencyType"] == 1 for v in b["buttons"])
    ]
    event_ids = current_events(timestamp)
    events = [b for b in banners if b["id"] in event_ids]
    anniversary = [b for b in eligible if family(b["name"])]
    general = sorted(
        [b for b in eligible if not family(b["name"]) and b["id"] not in event_ids],
        key=lambda b: b["id"],
    )
    # Six regular Iris/free offers ensure empty ticket inventories cannot shrink
    # the visible lineup. Event banners are additional, never displaced by these.
    offset = (month_of(timestamp) * 6) % len(general)
    regular = [general[(offset + i) % len(general)] for i in range(6)]
    regular_ids = {b["id"] for b in regular}
    general = [b for b in general if b["id"] not in regular_ids]

    def select(pool):
        pool = sorted(pool, key=lambda b: b["id"])
        offset = (int(timestamp // 86400) * 2) % len(pool)
        return [pool[(offset + i) % len(pool)] for i in range(2)]

    extra = [by_id[i] for i in permanent_ticket_ids() if i not in TICKET_BANNERS]
    result = {
        b["id"]: b
        for b in fixed
        + regular
        + select(general)
        + select(anniversary)
        + events
        + extra
    }
    return [b for b in result.values() if not consumed(b, progress, timestamp)]


@functools.lru_cache(maxsize=4)
def month_windows(month):
    """Preload one original record per offer with its actual native dates."""
    from guild_quests import month_window

    start, end = month_window(month)
    windows = {}
    for day in range(start // 86400, end // 86400 + 1):
        for banner in active(0, day * 86400):
            lid = banner["id"]
            if lid in permanent_ticket_ids():
                windows[lid] = (0, 4102444800)
                continue
            previous = windows.get(lid)
            day_start = day * 86400
            day_end = day_start + 86400 - 1
            if previous:
                if previous[1] + 1 != day_start:
                    raise ValueError(
                        "A banner has disjoint native availability windows"
                    )
                windows[lid] = (previous[0], day_end)
            else:
                windows[lid] = (day_start, day_end)
    return windows
