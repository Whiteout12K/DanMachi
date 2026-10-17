"""English display labels without replacing original artwork or gameplay rules.

Reading guide: display_name() supplies menu labels; master_asset() patches only
selected native display strings. Artwork and audio retain their existing sources.
Editing notes: preserve original identities, aliases, costs, pools and audio.
Checks: test_english_presentation.py and the Gacha/event focused suites.
"""

import functools
import json
import re
import struct
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JAPANESE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u3400-\u9fff]")
MASTER_PREFIX = "1/master/divide_enc/"


@functools.lru_cache(maxsize=1)
def text_policy():
    """Load explicit English display changes, never player/account data."""
    return json.loads((ROOT / "english-text.json").read_text())["tables"]


def display_name(table, identity, original, column=2):
    """Keep English originals unless a reviewed label translation exists."""
    return (
        text_policy().get(table, {}).get(str(identity), {}).get(str(column), original)
    )


def patch_text(name, data):
    """Append replacement strings and retarget only their FlatBuffer fields.

    Appending allows longer English translations without moving existing rows.
    Original string storage stays intact; IDs and scalar field offsets do not move.
    """
    import rebuild_master as master
    from build_gacha import value
    from gacha import encode

    result = bytearray(data)
    changes = text_policy().get(name, {})
    for row in master.rows(data):
        translated = changes.get(str(value(data, row, 0)), {})
        for column, text in translated.items():
            if JAPANESE.search(text):
                raise ValueError("English display policy contains Japanese text")
            field = master.fields(data, row)[int(column)]
            if not field:
                raise ValueError("Display field is absent: " + name)
            # String vectors contain the encrypted UTF-8 payload length and bytes.
            encoded = encode(text.encode() + b"\0", master.INNER_KEY)
            result.extend(b"\0" * (-len(result) % 4))
            pointer = len(result)
            result.extend(struct.pack("<I", len(encoded)) + encoded + b"\0")
            struct.pack_into("<I", result, field, pointer - field)
    return bytes(result)


def crypt(data, decrypt=False):
    """Use the retained master encryption envelope with the system OpenSSL."""
    import rebuild_master as master

    args = ["/usr/bin/openssl", "enc"]
    if decrypt:
        args.append("-d")
    args += ["-aes-256-cbc", "-K", master.AES_KEY.hex(), "-iv", master.IV.hex()]
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


@functools.lru_cache(maxsize=12)
def master_asset(name):
    """Compose English labels after the existing availability/validity overlays."""
    from asset_store import MemoryAsset
    import rebuild_master as master

    if name == "lottery":
        from gacha import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "gachaTicket":
        from gacha_ticket_access import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "adventureEpisode":
        from anniversary_events import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "shop":
        from anniversary_events import shop_master_asset

        data = zlib.decompress(
            crypt(shop_master_asset(MASTER_PREFIX + name + ".enc").data, decrypt=True)
        )
    else:
        data = master.table(name)
    return MemoryAsset(crypt(zlib.compress(patch_text(name, data))))


def apply_catalog(catalogue):
    """Keep native file sizes consistent with English display-label overlays."""
    for name in text_policy():
        path = MASTER_PREFIX + name + ".enc"
        if path in catalogue:
            catalogue[path] = {
                **catalogue[path],
                "size": master_asset(name).stat().st_size,
            }
