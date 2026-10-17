"""Offline equal weights for the retained beginner tutorial pool only."""

# Reading guide: Beginner pool compatibility: generate equal weights for the retained
# tutorial choices.
# Editing notes: This applies only to the beginner tutorial pool; standard Gacha pools
# keep their original weights.
# Checks: offline/test_tutorial_weights.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools
import struct
import subprocess
import zlib
from asset_store import MemoryAsset

PATH = "1/master/divide_enc/lotteryWeightGroup.enc"
GROUP = 174000013


def table_bytes():
    """
    Build the beginner pool compatibility weight table in the original binary
    format.
    """
    import rebuild_master as m
    from gacha import encode

    # FlatBuffer: root->vector->one row, two encrypted int32 scalar fields.
    b = bytearray(60)
    struct.pack_into("<I", b, 0, 12)
    struct.pack_into("<HHH", b, 4, 6, 8, 4)
    struct.pack_into("<iI", b, 12, 8, 4)
    struct.pack_into("<II", b, 20, 1, 16)
    struct.pack_into("<HHHH", b, 28, 8, 20, 4, 12)
    struct.pack_into("<i", b, 40, 12)
    b[44:52] = encode(struct.pack("<i", GROUP), m.INNER_KEY)
    b[52:60] = encode(struct.pack("<i", 1), m.INNER_KEY)
    return bytes(b)


@functools.lru_cache(maxsize=1)
def asset():
    """Expose encrypted tutorial weights as a read-only in-memory asset."""
    import rebuild_master as m

    # Guard the scope against changes to the original beginner pool.
    from build_gacha import value

    lottery = m.table("lottery")
    row = next(t for t in m.rows(lottery) if value(lottery, t, 0) == 171001765)
    group = value(lottery, row, 7)
    members = m.table("lotteryCharacter")
    weights = {
        value(members, t, 3) for t in m.rows(members) if value(members, t, 1) == group
    }
    if weights != {GROUP}:
        raise ValueError("Beginner weight groups changed")
    body = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-aes-256-cbc",
            "-K",
            m.AES_KEY.hex(),
            "-iv",
            m.IV.hex(),
        ],
        input=zlib.compress(table_bytes()),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(body)
