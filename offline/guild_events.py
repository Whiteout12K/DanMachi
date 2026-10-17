"""Match rotating Guild goals to retained offline story episodes."""

# Reading guide: Event calendar: link retained event episodes to rotating Guild goals
# and native availability.
# Editing notes: Keep episode matching separate from date changes so a scheduled quest
# still points to its original story.
# Checks: tools/maintain.py test events.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools
import subprocess
import zlib
from asset_store import MemoryAsset

NAMES = (
    "adventure",
    "adventureEpisode",
    "adventureStage",
    "shop",
    "shopProduct",
    "eventBox",
    "adventureMapInfo",
)
PATHS = tuple("1/master/divide_enc/" + name + ".enc" for name in NAMES)


@functools.lru_cache(maxsize=1)
def episode_links():
    """Map retained episode aliases to original episode/adventure identities."""
    import rebuild_master as m
    from build_gacha import value

    parents = m.table("adventure")
    offline_parents = {
        value(parents, t, 0)
        for t in m.rows(parents)
        if value(parents, t, 2) in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 16)
    }
    b = m.table("adventureEpisode")
    return {
        m.text(b, t, 1): (value(b, t, 0), value(b, t, 2), m.text(b, t, 15))
        for t in m.rows(b)
        if value(b, t, 2) in offline_parents
    }


def quest_episode(data, row):
    """Resolve the story episode referenced by a Guild quest definition."""
    import rebuild_master as m

    # An explicit original episode alias is a reliable offline target. Retired
    # server-ranked modes are not included in this completable story rotation.
    return episode_links().get(m.text(data, row, 10))


@functools.lru_cache(maxsize=1)
def schedule():
    """Build the event availability calendar used by quests and banners."""
    import rebuild_master as m
    import guild_quests as g

    b = m.table("achievement")
    windows = g.limited_windows(b, g.SESSION_MONTH)
    result = {}
    for row, window in windows.items():
        episode = quest_episode(b, row)
        if episode:
            eid = episode[0]
            if eid not in result or window[0] < result[eid][0]:
                result[eid] = window
    from gacha_rotation import supplementary_windows

    for eid, window in supplementary_windows(result, g.SESSION_MONTH).items():
        result.setdefault(eid, window)
    return result


def patch(data, name):
    """Apply scheduled availability to the requested retained event master."""
    import struct
    import rebuild_master as m
    from build_gacha import value
    from gacha import encode

    events = schedule()
    links = episode_links()
    parents = {p for eid, p, shop in links.values() if eid in events}
    shop_windows = {}
    for eid, parent, shop in links.values():
        if eid in events and shop:
            window = events[eid]
            if shop not in shop_windows or window[0] < shop_windows[shop][0]:
                shop_windows[shop] = window
    box_windows = {}
    episodes = m.table("adventureEpisode")
    for row in m.rows(episodes):
        eid = value(episodes, row, 0)
        alias = m.text(episodes, row, 23)
        if eid in events and alias:
            box_windows[alias] = events[eid]
    selected_shops = {}
    if name == "shopProduct":
        shops = m.table("shop")
        selected_shops = {
            value(shops, t, 0): shop_windows[m.text(shops, t, 1)]
            for t in m.rows(shops)
            if m.text(shops, t, 1) in shop_windows
        }
    result = bytearray(data)
    for row in m.rows(data):
        fields = m.fields(data, row)
        window = None
        columns = ()
        if name == "adventure" and value(data, row, 0) in parents:
            window = (0, 0)
            columns = (6, 7)
        elif name == "adventureEpisode":
            window = events.get(value(data, row, 0))
            columns = (6, 7)
        elif name == "adventureStage":
            window = events.get(value(data, row, 1))
            columns = (12, 13)
        elif name == "eventBox":
            window = box_windows.get(m.text(data, row, 2))
            columns = (6, 7)
        elif name == "shop":
            window = shop_windows.get(m.text(data, row, 1))
            columns = (4, 5)
        elif name == "shopProduct":
            window = selected_shops.get(value(data, row, 14))
            columns = (12, 13)
        if window is None:
            continue
        for col, date in zip(columns, window):
            if fields[col]:
                if len(m.decode(data[fields[col] : fields[col] + 12])) != 8:
                    raise ValueError("Event date format changed")
                result[fields[col] : fields[col] + 12] = encode(
                    struct.pack("<q", date), m.INNER_KEY
                )
        if (
            name == "adventureEpisode"
            and len(fields) > 24
            and fields[24]
            and m.text(data, row, 23)
        ):
            result[fields[24] : fields[24] + 12] = encode(
                struct.pack("<q", window[1]), m.INNER_KEY
            )
    return bytes(result)


@functools.lru_cache(maxsize=len(PATHS))
def asset(path):
    """Encrypt and expose a scheduled event master as in-memory bytes."""
    import rebuild_master as m
    import anniversary_events as anniversary

    if path not in PATHS:
        raise ValueError("Unsupported rotating event table")
    name = path.rsplit("/", 1)[1][:-4]
    # Compose existing permanent anniversary unlocks with monthly event windows.
    if name == "adventureEpisode":
        data = anniversary.patch_table(m.table(name))
    elif name == "adventureStage":
        data = anniversary.patch_stage_table(m.table(name))
    elif name == "eventBox":
        data = anniversary.patch_box_table(m.table(name))
    elif name == "adventureMapInfo":
        data = anniversary.patch_map_table(m.table(name))
    elif name in ("shop", "shopProduct"):
        data = anniversary.patch_shop_table(m.table(name), name == "shopProduct")
    else:
        data = m.table(name)
    # Keep the previously user-requested permanent anniversary availability.
    patched = patch(data, name)
    if name == "adventureEpisode":
        patched = anniversary.patch_table(patched)
    elif name == "adventureStage":
        patched = anniversary.patch_stage_table(patched)
    elif name == "eventBox":
        patched = anniversary.patch_box_table(patched)
    elif name == "adventureMapInfo":
        patched = anniversary.patch_map_table(patched)
    elif name in ("shop", "shopProduct"):
        patched = anniversary.patch_shop_table(patched, name == "shopProduct")
    encrypted = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-aes-256-cbc",
            "-K",
            m.AES_KEY.hex(),
            "-iv",
            m.IV.hex(),
        ],
        input=zlib.compress(patched),
        capture_output=True,
        check=True,
    ).stdout
    m.decode.cache_clear()
    return MemoryAsset(encrypted)
