"""Keep the six original anniversary stories open together, using ZIP media."""

# Reading guide: Anniversary overlays: open retained story, stage, exchange and box
# records in memory.
# Editing notes: Patch only documented availability fields. Keep original identities,
# prerequisites and rewards; Grand Day native entry repair lives in launcher/.
# Checks: tools/maintain.py test events.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools, struct, subprocess, zlib
from asset_store import MemoryAsset

EPISODES = (
    7160000101,
    7160000201,
    7160000301,
    7160000401,
    7160000501,
    7160000601,
    7160000701,
    7160000801,
    7160000901,
    7160001301,
    7160001401,
    7160001501,
    7160001901,
    7160002001,
    7160002101,
)
MASTER = "1/master/divide_enc/adventureEpisode.enc"
STAGE_MASTER = "1/master/divide_enc/adventureStage.enc"
FINAL_SCRIPT = "1/master/divide_novel_command_enc/novelCommand751040550.enc"
START = 0  # Native menu treats zero as unrestricted and bypasses its 2019 cutoff.
END = 4102444800  # 2100; deliberately independent of the computer's clock.


def patch_table(data):
    """
    Rewrite anniversary episode availability while keeping original row identities.
    """
    import rebuild_master as m
    from gacha import encode

    result = bytearray(data)
    seen = set()
    for row in m.rows(data):
        try:
            identity = m.scalar(data, row, 0, 8)
        except (ValueError, AssertionError):
            identity = m.scalar(data, row, 0, 4)
        if identity not in EPISODES:
            continue
        if m.scalar(data, row, 2, 8) != 671600001:
            raise ValueError("Unexpected anniversary group")
        fields = m.fields(data, row)
        for column, value in ((6, START), (7, END)):
            if not fields[column]:
                raise ValueError("Anniversary availability field missing")
            old = m.decode(bytes(result[fields[column] : fields[column] + 12]))
            if len(old) != 8:
                raise ValueError("Unexpected anniversary date format")
            result[fields[column] : fields[column] + 12] = encode(
                struct.pack("<q", value), m.INNER_KEY
            )
        # The book shortcut has a separate reward-box deadline.
        if len(fields) > 24 and fields[24] and m.text(data, row, 23):
            result[fields[24] : fields[24] + 12] = encode(
                struct.pack("<q", END), m.INNER_KEY
            )
        seen.add(identity)
    if seen != set(EPISODES):
        raise ValueError("Missing original anniversary episode")
    return bytes(result)


@functools.lru_cache(maxsize=1)
def anniversary_box_aliases():
    """Collect original box aliases linked to the retained anniversary stories."""
    import rebuild_master as m
    from build_gacha import value

    data = m.table("adventureEpisode")
    return frozenset(
        m.text(data, row, 23)
        for row in m.rows(data)
        if value(data, row, 0) in EPISODES and m.text(data, row, 23)
    )


def patch_box_table(data):
    """Keep each linked anniversary box available with its original contents."""
    import rebuild_master as m
    from gacha import encode

    aliases = anniversary_box_aliases()
    seen = set()
    result = bytearray(data)
    for row in m.rows(data):
        alias = m.text(data, row, 2)
        if alias not in aliases:
            continue
        seen.add(alias)
        fields = m.fields(data, row)
        for column, value in ((6, START), (7, END)):
            if not fields[column]:
                continue
            offset = fields[column]
            if len(m.decode(data[offset : offset + 12])) != 8:
                raise ValueError("Unexpected anniversary box date format")
            result[offset : offset + 12] = encode(struct.pack("<q", value), m.INNER_KEY)
    if seen != aliases:
        raise ValueError("Missing linked anniversary reward box")
    return bytes(result)


@functools.lru_cache(maxsize=1)
def master_asset():
    """Encrypt the in-memory anniversary episode overlay for native loading."""
    import rebuild_master as m

    data = patch_table(m.table("adventureEpisode"))
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
        input=zlib.compress(data),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(encrypted)


def patch_stage_table(data):
    """Match stage display availability to the enabled anniversary episodes."""
    import rebuild_master as m
    from gacha import encode

    result = bytearray(data)
    seen = set()
    for row in m.rows(data):
        episode = m.scalar(data, row, 1, 8)
        if episode not in EPISODES:
            continue
        seen.add(episode)
        fields = m.fields(data, row)
        for column, value in ((12, START), (13, END)):
            if not fields[column]:
                raise ValueError("Anniversary stage availability missing")
            offset = fields[column]
            if len(m.decode(data[offset : offset + 12])) != 8:
                raise ValueError("Unexpected stage date format")
            result[offset : offset + 12] = encode(struct.pack("<q", value), m.INNER_KEY)
    if seen != set(EPISODES):
        raise ValueError("Missing anniversary stages")
    return bytes(result)


@functools.lru_cache(maxsize=1)
def stage_master_asset():
    """Encrypt the stage overlay without changing its original reward definitions."""
    import rebuild_master as m

    data = patch_stage_table(m.table("adventureStage"))
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
        input=zlib.compress(data),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(encrypted)


SHOP_MASTERS = ("1/master/divide_enc/shop.enc", "1/master/divide_enc/shopProduct.enc")


@functools.lru_cache(maxsize=1)
def anniversary_shop_ids():
    """Find original exchange shops belonging to anniversary episodes."""
    import rebuild_master as m

    episodes = m.table("adventureEpisode")
    aliases = {
        m.text(episodes, row, 15)
        for row in m.rows(episodes)
        if m.scalar(episodes, row, 0, 8) in EPISODES
    }
    shops = m.table("shop")
    selected = {
        m.scalar(shops, row, 0, 4)
        for row in m.rows(shops)
        if m.text(shops, row, 1) in aliases
    }
    if len(selected) != len(aliases) or len(aliases) != len(EPISODES):
        raise ValueError("Missing anniversary exchange shop")
    return frozenset(selected)


def patch_shop_table(data, products=False):
    """Remove only availability dates, including each shop item's deadline."""
    import rebuild_master as m
    from gacha import encode

    result = bytearray(data)
    ids = anniversary_shop_ids()
    seen = set()
    for row in m.rows(data):
        shop = m.scalar(data, row, 14 if products else 0, 4)
        if shop not in ids:
            continue
        seen.add(shop)
        fields = m.fields(data, row)
        for column in ((12, 13) if products else (4, 5)):
            offset = fields[column]
            if not offset:
                continue  # Missing date already means unrestricted.
            if len(m.decode(data[offset : offset + 12])) != 8:
                raise ValueError("Unexpected shop date format")
            result[offset : offset + 12] = encode(struct.pack("<q", 0), m.INNER_KEY)
    if seen != ids:
        raise ValueError("Missing anniversary shop records")
    return bytes(result)


@functools.lru_cache(maxsize=2)
def shop_master_asset(path):
    """Serve the requested original shop master with availability overlays."""
    import rebuild_master as m

    if path not in SHOP_MASTERS:
        raise ValueError("Unknown exchange master")
    name = path.rsplit("/", 1)[1].removesuffix(".enc")
    data = patch_shop_table(m.table(name), products=name == "shopProduct")
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
        input=zlib.compress(data),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(encrypted)


def patch_map_table(data):
    # Grand Day now uses the original ordinary stage-list controller through a
    # guarded native dispatch. Keep every original map record untouched.
    """Return the original map bytes; native entry repair now handles Grand Day."""
    return data
